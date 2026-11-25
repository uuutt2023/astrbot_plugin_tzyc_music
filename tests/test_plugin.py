import ast
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import web

from .support import (
    Config,
    Event,
    StarTools,
    account_payload,
    api_module,
    auth,
    main_module,
    serve,
)


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.cfg = Config(
            ncm_api_external_enabled=True,
            ncm_api_base="http://external.invalid",
            ncm_web_enabled=False,
            send_play_card=False,
            send_comment_card=False,
            send_lyrics_forward=False,
            load_mode="file",
        )
        with patch.object(StarTools, "get_data_dir", return_value=self.data):
            self.plugin = main_module.NcmPlayerPlugin(None, self.cfg)
        self.addAsyncCleanup(self.plugin.terminate)

    async def test_source_switches_allow_all_four_combinations(self):
        for inner in (False, True):
            for outer in (False, True):
                self.cfg["ncm_api_embedded"] = inner
                self.cfg["ncm_api_external_enabled"] = outer
                self.plugin._update_sources("http://inner.invalid" if inner else "")
                self.assertEqual(
                    [url for _, url in self.plugin.api.api_sources],
                    (["http://inner.invalid"] if inner else [])
                    + (["http://external.invalid"] if outer else []),
                )

    async def test_delete_persists_off_and_reinstall_enables(self):
        server = self.plugin.embedded
        server.runtime_dir.mkdir(parents=True)
        (server.runtime_dir / "anonymous_token").write_text("owned cache")
        (server.dir / "executable").write_text("owned binary")
        self.plugin.cookie_file.write_text("MUSIC_U=preserved")
        self.cfg["ncm_api_embedded"] = True
        with patch.object(self.plugin, "_probe_accounts", new_callable=AsyncMock):
            message = await self.plugin._manage_api(False)
            self.assertIn("已删除", message)
            self.assertFalse(self.cfg.saved["ncm_api_embedded"])
            self.assertFalse(server.dir.exists())
            self.assertTrue(self.plugin.cookie_file.exists())
            self.assertEqual(
                self.plugin.api.api_sources, [("外部 API", "http://external.invalid")]
            )
            with patch.object(
                server,
                "reinstall",
                new_callable=AsyncMock,
                return_value=server.base_url,
            ) as reinstall:
                await self.plugin._manage_api(True)
                reinstall.assert_awaited_once()
            self.assertTrue(self.cfg.saved["ncm_api_embedded"])
            self.assertEqual(
                self.plugin.api.api_sources[0], ("内置 API", server.base_url)
            )

    async def test_config_save_failure_does_not_delete(self):
        self.cfg["ncm_api_embedded"] = True
        with (
            patch.object(self.cfg, "save_config", side_effect=OSError("denied")),
            patch.object(
                self.plugin.embedded,
                "remove",
                new_callable=AsyncMock,
            ) as remove,
        ):
            result = await self.plugin._manage_api(False)
            self.assertIn("操作已取消", result)
            self.assertTrue(self.cfg["ncm_api_embedded"])
            remove.assert_not_awaited()

    async def test_failed_audio_download_reaches_mirror_and_outer(self):
        requests = []

        async def handler(request):
            requests.append(request.path)
            if request.path == "/song/url/v1":
                return web.json_response(
                    {"data": [{"url": base + "/broken", "level": "standard"}]}
                )
            if request.path in ("/broken", "/mirror"):
                return web.Response(text="not audio", content_type="text/html")
            if request.path == "/outer":
                return web.Response(body=b"audio fixture", content_type="audio/mpeg")
            return web.json_response({"code": 200})

        async with serve(handler) as base:
            api = self.plugin.api
            api.set_api_sources([("本地测试", base)])
            api.meting_api = base + "/mirror"
            api.OUTER_URL = base + "/outer"
            self.cfg["quality"] = "standard"
            self.plugin.sender.send = AsyncMock(return_value="语音")
            event = Event()
            # 真实下载失败仍测试两次请求，仅省略生产环境的重试退避时间。
            with patch.object(api_module.asyncio, "sleep", new_callable=AsyncMock):
                result = await self.plugin._play(
                    event, api_module.Song(1, "测试", "歌手")
                )
            self.assertIn("官方外链", result)
            self.assertEqual(
                requests,
                ["/song/url/v1", "/broken", "/broken", "/mirror", "/mirror", "/outer"],
            )
            play = self.plugin.sender.send.call_args.args[2]
            path = self.plugin.sender.send.call_args.args[3]
            self.assertEqual(play.source, "outer")
            self.assertEqual(Path(path).read_bytes(), b"audio fixture")
            # 协议端可能仍在读取成功下载的文件，手动清缓存不能提前删掉它。
            _ = [text async for text in self.plugin.cmd_clear_cache(event)]
            self.assertTrue(Path(path).exists())
            self.plugin._expire_audio(Path(path))
            self.assertFalse(Path(path).exists())

    async def test_cancelled_download_removes_partial_and_releases_cache_guard(self):
        started, hold = asyncio.Event(), asyncio.Event()

        async def download(url, dest, **kwargs):
            Path(dest).write_bytes(b"partial")
            started.set()
            await hold.wait()

        with patch.object(self.plugin.api, "download", side_effect=download):
            task = asyncio.create_task(
                self.plugin._download(
                    api_module.Song(1, "测试", "歌手"),
                    api_module.PlayInfo(url="https://audio.invalid"),
                )
            )
            await asyncio.wait_for(started.wait(), 2)
            paths = list(self.plugin._active_downloads)
            self.assertEqual(len(paths), 1)
            _ = [text async for text in self.plugin.cmd_clear_cache(Event())]
            self.assertTrue(paths[0].exists())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(paths[0].exists())
            self.assertEqual(self.plugin._active_downloads, set())

    async def test_login_persistence_normalizes_and_rejects_stale_generation(self):
        async def handler(request):
            if request.path == "/login/status":
                return web.json_response(account_payload("correct"))
            return web.json_response({"code": 200, "data": {}})

        async with serve(handler) as base:
            raw = "__csrf=a; Path=/;MUSIC_U=user==; Max-Age=42"
            candidate = api_module.NetEaseAPI(ncm_api_base=base, cookie=raw)
            self.addAsyncCleanup(candidate.close)
            result = await self.plugin._save_login(raw, candidate, 0, "扫码")
            self.assertIn("UID correct", result)
            self.assertEqual(
                self.plugin.cookie_file.read_text(), "__csrf=a; MUSIC_U=user=="
            )
            self.assertEqual(self.plugin.api.account.uid, "correct")
            self.plugin._login_generation += 1
            candidate.set_cookie("MUSIC_U=other")
            result = await self.plugin._save_login(
                "MUSIC_U=other", candidate, 0, "扫码"
            )
            self.assertIn("取消", result)
            self.assertEqual(
                self.plugin.cookie_file.read_text(), "__csrf=a; MUSIC_U=user=="
            )

    async def test_diagnostic_reports_identity_without_cookie_values(self):
        self.plugin.api.set_api_sources([])
        self.plugin.api.set_cookie("MUSIC_U=private-token")
        self.plugin.api.account = auth.AccountState(
            login_valid=True,
            uid="1001",
            nickname="测试昵称",
            user_name="13800000000",
            membership="VIP",
        )
        with patch.object(self.plugin, "_probe_accounts", new_callable=AsyncMock):
            messages = [text async for text in self.plugin.cmd_diagnose(Event())]
        report = "\n".join(messages)
        self.assertIn("1001", report)
        self.assertIn("测试昵称", report)
        self.assertNotIn("private-token", report)
        self.assertNotIn("13800000000", report)

    async def test_schema_defaults_and_version_match(self):
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["ncm_api_log_output"]["default"])
        self.assertFalse(schema["ncm_web_cookie_enabled"]["default"])
        self.assertTrue(schema["ncm_api_external_enabled"]["default"])
        self.assertEqual(schema["ncm_api_github_accelerators"]["type"], "list")
        metadata = dict(
            line.split(": ", 1)
            for line in (root / "metadata.yaml")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.startswith(("name: ", "version: ", "repo: "))
        )
        module = ast.parse((root / "main.py").read_text(encoding="utf-8"))
        plugin = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "NcmPlayerPlugin"
        )
        registration = next(
            decorator
            for decorator in plugin.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "register"
        )
        self.assertEqual(metadata["name"], ast.literal_eval(registration.args[0]))
        self.assertEqual(
            metadata["version"].removeprefix("v"),
            ast.literal_eval(registration.args[3]),
        )
        self.assertEqual(metadata["name"], "astrbot_plugin_ncm_player")
        self.assertEqual(
            metadata["repo"], "https://github.com/TZYCeng/astrbot_plugin_tzyc_music"
        )


class HostApiSurfaceTests(unittest.TestCase):
    """插件只能 import 宿主**真实导出**的名字。

    v1.6.0 首次发布时写了 ``from astrbot.api.event import EventMessageType``，
    但真实 AstrBot 的 ``astrbot.api.event`` 并不导出它（只有
    AstrMessageEvent / MessageChain 等 6 个名字），插件因此在安装阶段
    直接 ImportError、根本装不上。这个测试把那条边界钉死。
    """

    # 与 astrbot/api/event/__init__.py 的 __all__ 保持一致
    ASTRBOT_API_EVENT_EXPORTS = {
        "AstrMessageEvent",
        "CommandResult",
        "EventResultType",
        "MessageChain",
        "MessageEventResult",
        "ResultContentType",
    }
    # filter 是 astrbot.api.event 的**子模块**（不在 __all__ 里，但
    # `from astrbot.api.event import filter` 是 Python 允许的用法）
    ASTRBOT_API_EVENT_SUBMODULES = {"filter"}

    def _imported_names(self) -> set[str]:
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("astrbot."):
                    names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("astrbot."):
                        names.add(alias.name.rsplit(".", 1)[-1])
        return names

    def test_only_imports_names_the_host_actually_exports(self):
        """从 astrbot.api.event 直接 import 的名字，必须在它的 __all__ 里。"""
        source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "astrbot.api.event":
                for alias in node.names:
                    self.assertTrue(
                        alias.name in self.ASTRBOT_API_EVENT_EXPORTS
                        or alias.name in self.ASTRBOT_API_EVENT_SUBMODULES,
                        f"astrbot.api.event 不导出 {alias.name}，插件会装不上",
                    )

    def test_event_message_type_is_importable_from_the_real_host(self):
        """EventMessageType 必须从真实存在的位置导入。"""
        from .support import main_module

        self.assertTrue(hasattr(main_module, "EventMessageType"))

    def test_filter_submodule_is_importable(self):
        """filter 是子模块：from astrbot.api.event import filter 必须可用。"""
        from astrbot.api.event import filter

        for attr in ("command", "regex", "llm_tool", "permission_type"):
            self.assertTrue(hasattr(filter, attr), f"filter 缺少 {attr}")

    def test_plugin_loads_under_real_host_export_surface(self):
        """在「真实 AstrBot 导出结构」的宿主下，插件必须能加载。

        这里不用测试桩（桩里我们会顺手补上缺的名字，掩盖问题），
        而是照着 astrbot/api/event/__init__.py 的真实 __all__ 搭一个最小宿主，
        再把插件当包加载——只要插件 import 了宿主并不导出的名字，
        就会在这一步 ImportError，和真实安装时一样。
        """
        import importlib.util
        import sys
        import types

        root = Path(__file__).resolve().parents[1]

        def make(name, **attrs):
            module = types.ModuleType(name)
            module.__dict__.update(attrs)
            sys.modules[name] = module
            return module

        def decorator(*args, **kwargs):
            return lambda target: target

        api_event = make(
            "astrbot.api.event",
            AstrMessageEvent=object,
            __all__=sorted(self.ASTRBOT_API_EVENT_EXPORTS),
        )
        # filter 是子模块：不在 api.event.__all__ 里，但可以被 import
        api_event.filter = make(
            "astrbot.api.event.filter",
            command=decorator,
            permission_type=decorator,
            llm_tool=decorator,
            regex=decorator,
            event_message_type=decorator,
            PermissionType=types.SimpleNamespace(ADMIN="admin"),
            EventMessageType=types.SimpleNamespace(ALL="all"),
        )
        make("astrbot")
        make(
            "astrbot.api",
            logger=types.SimpleNamespace(
                warning=lambda *a: None, error=lambda *a: None
            ),
            AstrBotConfig=dict,
        )
        make(
            "astrbot.api.message_components",
            **{k: object for k in ["Image", "Plain", "Record", "Node", "Nodes"]},
        )
        make(
            "astrbot.api.star",
            Star=object,
            StarTools=object,
            Context=object,
            register=decorator,
        )
        make("astrbot.core")
        make("astrbot.core.utils")
        make(
            "astrbot.core.utils.session_waiter",
            SessionController=object,
            session_waiter=decorator,
        )

        package = "probe_host_plugin"
        make(package, __path__=[str(root)])
        spec = importlib.util.spec_from_file_location(
            f"{package}.main", root / "main.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{package}.main"] = module
        try:
            spec.loader.exec_module(module)
        finally:
            for name in list(sys.modules):
                if name == package or name.startswith(f"{package}."):
                    del sys.modules[name]
        self.assertTrue(hasattr(module.NcmPlayerPlugin, "auto_parse"))
