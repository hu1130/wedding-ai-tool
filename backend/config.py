"""配置管理"""
import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # 阿里云百炼 API Key（通义万相 + AI试衣）
    aliyun_api_key: str = os.getenv("ALIYUN_DASHSCOPE_API_KEY", "").strip()

    # 应用配置
    upload_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    output_dir: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))

    # 场景预设
    scenes: dict = field(default_factory=lambda: {
        "教堂": "婚礼教堂，庄严神圣，彩色玻璃窗，鲜花装饰",
        "海边": "海边沙滩，日落黄昏，海浪拍岸，浪漫氛围",
        "花园": "欧洲花园，玫瑰盛开，喷泉，绿植拱门",
        "中式庭院": "中式园林，红灯笼，木质亭台，古典风格",
        "城堡": "欧式城堡，古典大厅，水晶吊灯，奢华风格",
        "森林": "森林深处，阳光透过树叶，野花遍地，自然风格",
        "影棚": "高端婚纱摄影影棚，柔和棚拍灯光，纯净浅色背景，时尚杂志质感",
        "天台夜景": "城市天台夜景，远处灯光虚化，香槟色氛围灯，现代高级感",
    })


settings = Settings()
