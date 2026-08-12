"""风格约束链路测试。

覆盖 Art Director 的硬约束合并，以及 Prompt Compiler 对首轮风格参考图、
正向风格契约和负向禁用项的确定性编译。测试不会调用外部 API。
"""

import asyncio
import unittest

from app.agents.supervisor_agent import make_supervisor_prepare
from app.agents.workflow_compiler import make_prompt_compiler


class _FakeRuntime:
    """返回预设 Agent 输出的最小运行时替身。"""

    def __init__(self, output: dict):
        self.output = output

    async def call_json(self, **_kwargs):
        """模拟 AgentRuntime.call_json，并提供事件所需的调用 ID。"""

        return self.output, {"id": "inv_test"}


class StyleControlTests(unittest.TestCase):
    """验证硬风格约束不会被 Agent 输出或首次生成流程绕过。"""

    def test_supervisor_keeps_profile_visual_as_hard_contract(self):
        """模型与预设发生冲突时，应以项目 Style Profile 为准。"""

        async def run():
            runtime = _FakeRuntime(
                {
                    "style_bible": {
                        "camera": "写实透视",
                        "mood": "轻快冒险",
                    },
                    "audit_rules": [],
                }
            )
            node = make_supervisor_prepare(runtime)
            result = await node(
                {
                    "run_id": "run_test",
                    "project_id": "project_test",
                    "session_id": "session_test",
                    "turn_id": "turn_test",
                    "turn_sequence": 1,
                    "version_number": 1,
                    "user_request": "设计月下森林",
                    "locked_constraints": [],
                    "memory": {},
                    "reference_images": [],
                    "style_profile": {
                        "style_bible": {
                            "visual": {
                                "camera": "正交横版侧视角",
                                "pixel_rule": "统一像素密度",
                            }
                        }
                    }
                }
            )
            self.assertEqual(result["style_bible"]["camera"], "正交横版侧视角")
            self.assertEqual(result["style_bible"]["pixel_rule"], "统一像素密度")
            self.assertEqual(result["style_bible"]["mood"], "轻快冒险")

        asyncio.run(run())

    def test_first_turn_style_reference_uses_edit_mode_and_hard_prompts(self):
        """首轮上传风格图时也应使用编辑模式，并实际编入正负提示词。"""

        async def run():
            runtime = _FakeRuntime(
                {
                    "positive_prompt": "月下森林场景",
                    "negative_prompt": "模糊",
                }
            )
            node = make_prompt_compiler(runtime)
            result = await node(
                {
                    "project_id": "project_test",
                    "run_id": "run_test",
                    "turn_id": "turn_test",
                    "turn_sequence": 1,
                    "version_number": 1,
                    "user_request": "设计月下森林",
                    "aspect_ratio": "16:9",
                    "reference_images": ["/storage/references/style.png"],
                    "style_profile": {
                        "style_bible": {
                            "visual": {
                                "style_name": "原创横版沙盒像素风",
                                "camera": "正交横版侧视角",
                                "pixel_rule": "统一像素密度",
                                "forbidden": ["3D渲染", "抗锯齿边缘"],
                            }
                        }
                    },
                    "selected_concept": {},
                    "constraints": {"negative_constraints": ["文字水印"]},
                    "image_backend": "qwen_image",
                    "image_model": "qwen-image-2.0",
                }
            )
            request = result["workflow_request"]
            self.assertEqual(request["generation_mode"], "edit")
            self.assertEqual(request["reference_images"], ["/storage/references/style.png"])
            self.assertIn("正交横版侧视角", request["positive_prompt"])
            self.assertIn("只学习像素技法", request["positive_prompt"])
            self.assertIn("3D渲染", request["negative_prompt"])
            self.assertIn("抗锯齿边缘", request["negative_prompt"])
            self.assertIn("文字水印", request["negative_prompt"])
            self.assertLessEqual(request["seed"], 2147483647)

        asyncio.run(run())

    def test_second_turn_removal_overrides_parent_identity_and_old_prompt(self):
        """删除角色时必须置顶删除指令，并清除历史脚手架、角色诱导词和 LoRA 触发词。"""

        async def run():
            runtime = _FakeRuntime(
                {
                    "positive_prompt": (
                        "月下森林，小比例角色，s86b5p\n"
                        "必须遵守的风格契约：旧约束\n"
                        "参考图规则：所有输入图片都仅为风格参考"
                    ),
                    "negative_prompt": "模糊",
                }
            )
            node = make_prompt_compiler(runtime)
            result = await node(
                {
                    "project_id": "project_test",
                    "run_id": "run_remove",
                    "turn_id": "turn_remove",
                    "turn_sequence": 2,
                    "version_number": 2,
                    "user_request": "可以将小冒险者去掉吗，留下完整场景。",
                    "aspect_ratio": "1:1",
                    "reference_images": ["/storage/references/style.png"],
                    "parent_image": {"id": "img_parent", "file_path": "/storage/images/parent.png"},
                    "style_profile": {
                        "style_bible": {
                            "visual": {
                                "style_name": "原创横版沙盒像素风",
                                "shape_language": "模块化图格地形、小比例角色、清晰剪影",
                                "readability_rule": "前中后景清楚；角色与道具清晰",
                                "forbidden": ["3D渲染"],
                            },
                            "generation": {
                                "loras": [{"trigger_word": "s86b5p"}],
                            },
                        }
                    },
                    "selected_concept": {},
                    "constraints": {"negative_constraints": []},
                    "image_backend": "qwen_image",
                    "image_model": "qwen-image-2.0",
                }
            )
            request = result["workflow_request"]
            prompt = request["positive_prompt"]
            self.assertTrue(prompt.startswith("当前编辑指令（最高优先级）"))
            self.assertIn("完全移除“小冒险者”", prompt)
            self.assertIn("自然补全原先被遮挡的背景", prompt)
            self.assertIn("第1张图是必须编辑的父图", prompt)
            self.assertNotIn("小比例角色", prompt)
            self.assertNotIn("s86b5p", prompt)
            self.assertNotIn("旧约束", prompt)
            self.assertIn("小冒险者", request["negative_prompt"])
            self.assertIn("人物剪影", request["negative_prompt"])
            for variant in request["variants"]:
                self.assertNotIn("保留锁定元素与主体身份", variant["prompt_suffix"])

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
