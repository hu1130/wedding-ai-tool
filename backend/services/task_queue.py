"""任务队列 & 流水线编排（纯阿里云版）"""
import asyncio
import os
import shutil
from datetime import datetime
from typing import Optional

from backend.config import settings
from backend.models.task import Task, TaskStatus, StepStatus
from backend.services.aliyun_dress import AliyunTryOnService
from backend.services.wanx_scene import WanxSceneService
from backend.utils.composite import composite_subject_on_background
from backend.utils.garment import is_floor_length_gown


FACE_ARTIFACT_NEGATIVE_PROMPT = (
    "，贴脸，抠图头像，头像像贴纸，脸部硬边，头发边缘硬边，脸部边缘光晕，"
    "脸和脖子断裂，头身不连接，头部比例过大，脸部光线不一致，肤色不一致，"
    "pasted face, cutout head, sticker face, hard face edge, halo around head, "
    "disconnected neck, floating head, mismatched face lighting, mismatched skin tone"
)

ACTION_POSE_MODES = {"light", "experimental"}


def _is_action_pose(task: Task) -> bool:
    return (
        bool(getattr(task, "pose_reference_file", None))
        or getattr(task, "pose_mode", "stable") in ACTION_POSE_MODES
    )


class TaskPipeline:
    """任务流水线：AI试衣 → 场景生成"""

    def __init__(self):
        self.tryon = AliyunTryOnService()
        self.wanx = WanxSceneService()

    async def run_task(self, task_id: str):
        """执行单个任务的全流程"""
        task = Task.get(task_id)
        if not task:
            return

        task.status = TaskStatus.PROCESSING
        task.save()

        try:
            output_dir = os.path.join(settings.output_dir, task.task_id)
            os.makedirs(output_dir, exist_ok=True)

            current_image = task.model_file
            floor_length_gown = is_floor_length_gown(task.dress_file)
            action_pose = _is_action_pose(task)
            use_reference_gown = floor_length_gown or action_pose

            # ========== 第一步：AI试衣（换装） ==========
            task.steps["dress"] = StepStatus.PROCESSING
            task.progress = 10
            task.save()

            if use_reference_gown:
                # Full gowns and changed poses are more stable when the product
                # dress remains a direct reference in the final generation step.
                dress_result = task.dress_file
            else:
                dress_result = await self._step_tryon(task, output_dir)
                current_image = dress_result
            task.steps["dress"] = StepStatus.COMPLETED
            task.output_files["dress"] = dress_result
            task.progress = 50
            task.save()

            if task.face_swap:
                task.steps["face"] = StepStatus.FAILED
                task.error_message = "换脸步骤尚未实现"
                task.status = TaskStatus.FAILED
                task.save()
                return
            task.steps["face"] = StepStatus.SKIPPED

            # ========== 第二步：场景生成 ==========
            task.steps["scene"] = StepStatus.PROCESSING
            task.progress = 60
            task.save()

            if use_reference_gown:
                scene_result = await self._step_reference_gown_scene(
                    task,
                    output_dir,
                    force_floor_length=floor_length_gown or action_pose,
                )
                task.output_files["scene"] = scene_result
                current_image = scene_result
                task.steps["scene"] = StepStatus.COMPLETED
            elif getattr(task, "generation_mode", "stable") == "stable":
                background_result = await self._step_background(task, output_dir)
                task.output_files["scene"] = background_result
                current_image = composite_subject_on_background(
                    subject_image_path=current_image,
                    background_image_path=background_result,
                    output_dir=output_dir,
                )
                task.output_files["composite"] = current_image
                task.steps["scene"] = StepStatus.COMPLETED
            else:
                scene_result = await self._step_scene(
                    task,
                    current_image,
                    output_dir,
                )
                task.output_files["scene"] = scene_result
                task.steps["scene"] = StepStatus.COMPLETED
                current_image = scene_result
            task.progress = 90
            task.save()

            # ========== 输出最终结果 ==========
            if os.path.exists(current_image):
                extension = os.path.splitext(current_image)[1].lower() or ".jpg"
                if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
                    extension = ".jpg"
                final_path = os.path.join(output_dir, f"final{extension}")
                shutil.copy2(current_image, final_path)
                task.output_files["final"] = final_path
            else:
                task.status = TaskStatus.FAILED
                task.error_message = "最终结果文件不存在"
                task.save()
                return

            task.steps["upscale"] = StepStatus.SKIPPED
            task.progress = 100
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now().isoformat()
            task.save()

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            for step_name, step_status in task.steps.items():
                if step_status == StepStatus.PROCESSING:
                    task.steps[step_name] = StepStatus.FAILED
            task.save()

    async def _step_tryon(self, task: Task, output_dir: str) -> Optional[str]:
        """AI试衣步骤"""
        try:
            result = await self.tryon.try_on(
                model_image_path=task.model_file,
                garment_image_path=task.dress_file,
                output_dir=output_dir,
                restore_face=task.preserve_face and not task.face_swap,
            )
            return result
        except Exception as e:
            print(f"[AI试衣失败] {e}")
            raise RuntimeError(f"AI试衣失败: {e}") from e

    async def _step_scene(
        self,
        task: Task,
        current_image: str,
        output_dir: str,
        force_floor_length: bool = False,
    ) -> Optional[str]:
        """场景生成步骤"""
        try:
            prompt = self.wanx.build_scene_prompt(
                scene_name=task.scene,
                pose=task.pose,
                preserve_face=task.preserve_face,
                force_floor_length=force_floor_length,
                scene_prompt=task.scene_prompt,
            )
            negative_prompt = (
                "短裙，及膝裙，迷你裙，普通连衣裙，露出小腿，裙摆被截断，"
                "短款礼服，改变婚纱廓形，换脸，脸部变形，扭曲，变形，模糊，"
                "低质量，水印，文字"
            )
            negative_prompt += FACE_ARTIFACT_NEGATIVE_PROMPT
            result = await self.wanx.generate_scene(
                input_image_path=current_image,
                prompt=prompt,
                output_dir=output_dir,
                resolution=task.resolution,
                negative_prompt=negative_prompt,
            )
            return result
        except Exception as e:
            print(f"[场景生成失败] {e}")
            raise RuntimeError(f"场景生成失败: {e}") from e

    async def _step_reference_gown_scene(
        self,
        task: Task,
        output_dir: str,
        force_floor_length: bool = False,
    ) -> Optional[str]:
        """Generate a full-gown image from model + product dress references."""
        try:
            prompt = self.wanx.build_reference_gown_prompt(
                scene_name=task.scene,
                pose=task.pose,
                preserve_face=task.preserve_face,
                pose_mode=task.pose_mode,
                force_floor_length=force_floor_length,
                scene_prompt=task.scene_prompt,
                has_pose_reference=bool(task.pose_reference_file),
            )
            negative_prompt = (
                "两条裙子，双层裙，短裙外面套长裙，上下两件裙子，保留原短裙，"
                "及膝裙，迷你裙，普通连衣裙，露出小腿，裙摆断开，裙摆被截断，"
                "错误领口，错误腰线，改变婚纱款式，手部畸形，多余手指，换脸，脸部变形，扭曲，"
                "低质量，水印，文字，logo"
            )
            negative_prompt += FACE_ARTIFACT_NEGATIVE_PROMPT
            reference_image_paths = [task.dress_file]
            if task.pose_reference_file:
                reference_image_paths.append(task.pose_reference_file)

            return await self.wanx.generate_scene(
                input_image_path=task.model_file,
                prompt=prompt,
                output_dir=output_dir,
                resolution=task.resolution,
                negative_prompt=negative_prompt,
                reference_image_paths=reference_image_paths,
            )
        except Exception as e:
            print(f"[婚纱参考生成失败] {e}")
            raise RuntimeError(f"婚纱参考生成失败: {e}") from e

    async def _step_background(self, task: Task, output_dir: str) -> Optional[str]:
        """Generate an empty background for stable compositing."""
        try:
            return await self.wanx.generate_background(
                scene_name=task.scene,
                output_dir=output_dir,
                resolution=task.resolution,
                scene_prompt=task.scene_prompt,
            )
        except Exception as e:
            print(f"[背景生成失败] {e}")
            raise RuntimeError(f"背景生成失败: {e}") from e


# 全局任务队列
_task_queue: asyncio.Queue = None
_pipeline: Optional[TaskPipeline] = None


async def init_queue():
    """初始化任务队列"""
    global _task_queue
    if _task_queue is not None:
        return
    recovered = Task.recover_interrupted_processing_tasks()
    if recovered:
        print(f"[INFO] Recovered {recovered} interrupted processing task(s)")
    _task_queue = asyncio.Queue()
    asyncio.create_task(_queue_worker())


async def enqueue_task(task_id: str):
    """提交任务到队列"""
    if _task_queue is None:
        await init_queue()
    await _task_queue.put(task_id)


async def _queue_worker():
    """队列消费者"""
    global _pipeline
    while True:
        task_id = await _task_queue.get()
        try:
            if _pipeline is None:
                _pipeline = TaskPipeline()
            await _pipeline.run_task(task_id)
        except Exception as e:
            print(f"[队列错误] 任务 {task_id}: {e}")
            task = Task.get(task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.save()
        finally:
            _task_queue.task_done()
