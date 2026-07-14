import unittest

from backend.services.wanx_scene import (
    WanxSceneService,
    build_wedding_gown_negative_prompt,
)


class WeddingPromptingTest(unittest.TestCase):
    def setUp(self):
        self.service = WanxSceneService.__new__(WanxSceneService)

    def assertContainsAll(self, text: str, expected: list[str]):
        for item in expected:
            with self.subTest(item=item):
                self.assertIn(item, text)

    def test_reference_gown_prompt_preserves_floor_length_face_and_style(self):
        prompt = self.service.build_reference_gown_prompt(
            scene_name="影棚",
            pose="自然站立",
            preserve_face=True,
            pose_mode="light",
            force_floor_length=True,
            scene_prompt="柔和影棚光",
            has_pose_reference=True,
        )

        self.assertContainsAll(
            prompt,
            [
                "长款拖地婚纱",
                "拖尾",
                "落地长度",
                "不裁切裙摆",
                "严格保留第一张图中模特的五官",
                "不要换脸",
                "同一件完整婚纱",
                "严格保留原始领口",
                "腰线",
                "蕾丝",
                "不要简化成普通白裙",
                "第三张图是动作参考",
                "不要复制第三张图的人脸",
            ],
        )

    def test_scene_prompt_keeps_current_wedding_gown_constraints(self):
        prompt = self.service.build_scene_prompt(
            scene_name="海边",
            pose="保持原姿势",
            preserve_face=True,
            force_floor_length=False,
            scene_prompt="日落海边",
        )

        self.assertContainsAll(
            prompt,
            [
                "当前图片中的白色婚纱",
                "严格保留输入图片中人物的五官",
                "不要改变面部相似度",
                "同一件完整婚纱",
                "裙长",
                "拖尾",
                "如果参考婚纱是长款或带拖尾，不得缩短",
                "不要重新设计成其他裙子",
                "全身人像构图",
            ],
        )

    def test_negative_prompt_blocks_short_plain_dresses_and_face_artifacts(self):
        prompt = build_wedding_gown_negative_prompt(reference_mode=True)

        self.assertContainsAll(
            prompt,
            [
                "短裙",
                "及膝裙",
                "普通连衣裙",
                "普通白裙",
                "晚礼服",
                "露出小腿",
                "拖尾消失",
                "两条裙子",
                "保留原短裙",
                "没有完全替换原服装",
                "换脸",
                "五官漂移",
                "贴脸",
                "头身不连接",
            ],
        )


if __name__ == "__main__":
    unittest.main()
