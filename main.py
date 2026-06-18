import time
from datetime import datetime, timedelta
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Plain


@register(
    "astrbot_plugin_screenshot",
    "Marvis",
    "截图插件：对指定显示器进行截图并发送给用户，支持多显示器环境。",
    "1.0.0",
    "https://github.com/user/astrbot_plugin_screenshot",
)
class ScreenshotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._temp_dir = Path(__file__).parent / "temp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

        monitor_idx = int(self.config.get("monitor_index", 0))
        clean_days = int(self.config.get("auto_clean_days", 7))
        logger.info(
            f"截图插件已加载，目标显示器：{monitor_idx}，"
            f"自动清理：{'关闭' if clean_days <= 0 else f'{clean_days}天前'}"
        )

    # ---------- 清理逻辑 ----------

    def _clean_old_screenshots(self) -> int:
        """清理超过 auto_clean_days 天的旧截图，返回删除数量。"""
        clean_days = int(self.config.get("auto_clean_days", 7))
        if clean_days <= 0:
            return 0

        cutoff = datetime.now() - timedelta(days=clean_days)
        deleted = 0
        for p in self._temp_dir.glob("screenshot_*.png"):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
                if mtime < cutoff:
                    p.unlink()
                    deleted += 1
            except OSError:
                pass
        return deleted

    def _clean_all_screenshots(self) -> int:
        """删除 temp 目录下所有截图，返回删除数量。"""
        deleted = 0
        for p in self._temp_dir.glob("screenshot_*.png"):
            try:
                p.unlink()
                deleted += 1
            except OSError:
                pass
        return deleted

    # ---------- 命令 ----------

    @filter.permission_type(filter.PermissionType.MEMBER)
    @filter.command(
        "截图",
        alias={"截屏", "screen", "screenshot", "capture", "printscreen"},
        desc="对指定显示器截图并发送",
    )
    async def on_screenshot_command(self, event: AstrMessageEvent):
        """截图指令。"""
        monitor_idx = int(self.config.get("monitor_index", 0))

        # 截图前自动清理旧文件
        cleaned = self._clean_old_screenshots()
        if cleaned > 0:
            logger.info(f"自动清理了 {cleaned} 张旧截图")

        try:
            import mss
        except ImportError:
            logger.error("截图插件依赖 mss 未安装")
            yield event.plain_result(
                "截图功能依赖 mss 库未安装。请执行 pip install mss 并重启 AstrBot。"
            )
            return

        with mss.mss() as sct:
            all_monitors = sct.monitors
            real_count = len(all_monitors) - 1

            if real_count == 0:
                yield event.plain_result("未检测到任何显示器，截图失败。")
                return

            internal_idx = monitor_idx + 1
            if internal_idx >= len(all_monitors):
                logger.warning(
                    f"显示器索引 {monitor_idx} 超出范围，回退到主显示器"
                )
                internal_idx = 1
                fallback_msg = (
                    f"显示器 {monitor_idx} 不存在，已回退到主显示器 "
                    f"（共 {real_count} 个显示器，可用索引：0~{real_count - 1}）。\n"
                )
            else:
                fallback_msg = ""

            monitor = all_monitors[internal_idx]
            screenshot = sct.grab(monitor)
            if screenshot is None:
                yield event.plain_result("截图失败：无法获取屏幕数据。")
                return

            timestamp = int(time.time() * 1000)
            filename = f"screenshot_{monitor_idx}_{timestamp}.png"
            filepath = self._temp_dir / filename
            mss.tools.to_png(screenshot.rgb, screenshot.size, output=str(filepath))

        yield event.chain_result(
            [
                Plain(
                    fallback_msg
                    + f"显示器 {monitor_idx} 截图 "
                    f"({monitor['width']}×{monitor['height']})："
                ),
                Image(file=str(filepath.resolve())),
            ]
        )

        logger.info(f"截图已保存并发送：{filepath}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("清理截图", alias={"cleanscreenshot"}, desc="清理所有历史截图文件")
    async def on_clean_command(self, event: AstrMessageEvent):
        """手动清理 temp 目录下所有截图。"""
        deleted = self._clean_all_screenshots()
        if deleted == 0:
            yield event.plain_result("没有需要清理的截图文件。")
        else:
            yield event.plain_result(f"已清理 {deleted} 张历史截图。")
            logger.info(f"手动清理了 {deleted} 张截图")

    async def terminate(self) -> None:
        logger.info("截图插件已卸载。")
