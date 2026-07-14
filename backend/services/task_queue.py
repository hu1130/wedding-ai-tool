"""任务队列 & 流水线编排（纯阿里云版）"""
import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from backend.config import settings
from backend.logging_config import configure_logging
from backend.models.clothing import is_wedding_clothing
from backend.models.task import Task, TaskStatus, StepStatus
from backend.services.aliyun_dress import AliyunTryOnService
from backend.services.wanx_scene import WanxSceneService, build_clothing_negative_prompt
from backend.utils.composite import composite_subject_on_background
from backend.utils.garment import is_floor_length_gown
from backend.utils.image import persist_output_file


configure_logging()
logger = logging.getLogger(__name__)
ACTION_POSE_MODES = {"light", "experimental"}
NON_RETRYABLE_ERROR_TYPES = (FileNotFoundError, PermissionError, ValueError)


class NonRetryableTaskError(RuntimeError):
    """Failure that should be surfaced immediately instead of re-queued."""


def _current_failure_stage(task: Task) -> str:
    for step_name, step_status in task.steps.items():
        if step_status == StepStatus.PROCESSING:
            return step_name
    current_step, _ = task.current_step()
    return current_step or "unknown"


def _mark_processing_steps_failed(task: Task) -> None:
    for step_name, step_status in task.steps.items():
        if step_status == StepStatus.PROCESSING:
            task.steps[step_name] = StepStatus.FAILED


def _is_retryable_error(error: Exception) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, (NonRetryableTaskError, *NON_RETRYABLE_ERROR_TYPES)):
            return False
        current = current.__cause__ or current.__context__
    return True


def _record_task_failure(task: Task, error: Exception, stage: Optional[str] = None) -> bool:
    retryable = _is_retryable_error(error)
    failure_stage = stage or _current_failure_stage(task)
    now = datetime.now()

    _mark_processing_steps_failed(task)
    task.error_message = str(error)
    task.last_error_at = now.isoformat()
    task.last_error_stage = failure_stage

    if retryable and task.retry_count < task.max_retries:
        task.retry_count += 1
        task.status = TaskStatus.PENDING
        task.progress = 0
        if settings.task_retry_delay_seconds:
            task.next_retry_at = (
                now + timedelta(seconds=settings.task_retry_delay_seconds)
            ).isoformat()
        else:
            task.next_retry_at = ""
        task.save()
        logger.warning(
            "Task failed; scheduled retry task_id=%s stage=%s retry_count=%s max_retries=%s next_retry_at=%s error=%s",
            task.task_id,
            failure_stage,
            task.retry_count,
            task.max_retries,
            task.next_retry_at or "immediate",
            error,
        )
        return True

    task.status = TaskStatus.FAILED
    task.next_retry_at = ""
    task.save()
    if retryable:
        logger.error(
            "Task failed; retries exhausted task_id=%s stage=%s retry_count=%s max_retries=%s error=%s",
            task.task_id,
            failure_stage,
            task.retry_count,
            task.max_retries,
            error,
        )
    else:
        logger.error(
            "Task failed; non-retryable task_id=%s stage=%s retry_count=%s max_retries=%s error=%s",
            task.task_id,
            failure_stage,
            task.retry_count,
            task.max_retries,
            error,
        )
    return False


def _is_action_pose(task: Task) -> bool:
    return (
        bool(getattr(task, "pose_reference_file", None))
        or getattr(task, "pose_mode", "stable") in ACTION_POSE_MODES
    )


def _persist_task_output(task: Task, label: str, file_path: str) -> None:
    if not file_path:
        return
    try:
        task.output_files[label] = persist_output_file(file_path)
    except Exception as exc:
        if settings.object_storage_mode == "oss":
            raise
        logger.warning(
            "Output persistence skipped task_id=%s label=%s path=%s error=%s",
            task.task_id,
            label,
            file_path,
            exc,
        )
        task.output_files[label] = file_path


class TaskPipeline:
    """任务流水线：AI试衣 → 场景生成"""

    def __init__(self):
        self.tryon = AliyunTryOnService()
        self.wanx = WanxSceneService()

    async def run_task(self, task_id: str) -> bool:
        """执行单个任务的全流程"""
        task = Task.get(task_id)
        if not task:
            logger.info("Task skipped; not found task_id=%s", task_id)
            return False

        task.status = TaskStatus.PROCESSING
        task.next_retry_at = ""
        task.save()
        logger.info(
            "Task started task_id=%s retry_count=%s max_retries=%s",
            task.task_id,
            task.retry_count,
            task.max_retries,
        )

        try:
            output_dir = os.path.join(settings.output_dir, task.task_id)
            os.makedirs(output_dir, exist_ok=True)

            current_image = task.model_file
            wedding_mode = is_wedding_clothing(task.clothing_type)
            floor_length_gown = wedding_mode and is_floor_length_gown(task.dress_file)
            action_pose = _is_action_pose(task)
            use_reference_clothing = floor_length_gown or action_pose

            # ========== 第一步：AI试衣（换装） ==========
            task.steps["dress"] = StepStatus.PROCESSING
            task.progress = 10
            task.save()

            if use_reference_clothing:
                # Full gowns and changed poses are more stable when the product
                # garment remains a direct reference in the final generation step.
                dress_result = task.dress_file
            else:
                dress_result = await self._step_tryon(task, output_dir)
                current_image = dress_result
            task.steps["dress"] = StepStatus.COMPLETED
            _persist_task_output(task, "dress", dress_result)
            task.progress = 50
            task.save()

            if task.face_swap:
                task.steps["face"] = StepStatus.PROCESSING
                error = NonRetryableTaskError("Face swap step is not implemented")
                _record_task_failure(task, error, stage="face")
                return False
            task.steps["face"] = StepStatus.SKIPPED

            # ========== 第二步：场景生成 ==========
            task.steps["scene"] = StepStatus.PROCESSING
            task.progress = 60
            task.save()

            if use_reference_clothing:
                scene_result = await self._step_reference_clothing_scene(
                    task,
                    output_dir,
                    force_floor_length=floor_length_gown or (wedding_mode and action_pose),
                )
                _persist_task_output(task, "scene", scene_result)
                current_image = scene_result
                task.steps["scene"] = StepStatus.COMPLETED
            elif getattr(task, "generation_mode", "stable") == "stable":
                background_result = await self._step_background(task, output_dir)
                _persist_task_output(task, "scene", background_result)
                current_image = composite_subject_on_background(
                    subject_image_path=current_image,
                    background_image_path=background_result,
                    output_dir=output_dir,
                )
                _persist_task_output(task, "composite", current_image)
                task.steps["scene"] = StepStatus.COMPLETED
            else:
                scene_result = await self._step_scene(
                    task,
                    current_image,
                    output_dir,
                )
                _persist_task_output(task, "scene", scene_result)
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
                _persist_task_output(task, "final", final_path)
            else:
                error = NonRetryableTaskError("Final output file does not exist")
                _record_task_failure(task, error, stage="upscale")
                return False

            task.steps["upscale"] = StepStatus.SKIPPED
            task.progress = 100
            task.status = TaskStatus.COMPLETED
            task.error_message = ""
            task.last_error_stage = ""
            task.next_retry_at = ""
            task.completed_at = datetime.now().isoformat()
            task.save()
            logger.info(
                "Task completed task_id=%s retry_count=%s output_final=%s",
                task.task_id,
                task.retry_count,
                task.output_files.get("final", ""),
            )
            return False

        except Exception as e:
            stage = _current_failure_stage(task)
            if _is_retryable_error(e) and task.retry_count < task.max_retries:
                logger.warning(
                    "Task exception; will retry task_id=%s stage=%s retry_count=%s max_retries=%s error=%s",
                    task.task_id,
                    stage,
                    task.retry_count,
                    task.max_retries,
                    e,
                    exc_info=True,
                )
            else:
                logger.exception(
                    "Task exception task_id=%s stage=%s retry_count=%s max_retries=%s error=%s",
                    task.task_id,
                    stage,
                    task.retry_count,
                    task.max_retries,
                    e,
                )
            return _record_task_failure(task, e, stage=stage)

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
            logger.exception("Task step failed task_id=%s stage=dress error=%s", task.task_id, e)
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
            prompt = self.wanx.build_clothing_scene_prompt(
                scene_name=task.scene,
                clothing_type=task.clothing_type,
                pose=task.pose,
                preserve_face=task.preserve_face,
                force_floor_length=force_floor_length,
                scene_prompt=task.scene_prompt,
            )
            negative_prompt = build_clothing_negative_prompt(task.clothing_type)
            result = await self.wanx.generate_scene(
                input_image_path=current_image,
                prompt=prompt,
                output_dir=output_dir,
                resolution=task.resolution,
                negative_prompt=negative_prompt,
            )
            return result
        except Exception as e:
            logger.exception("Task step failed task_id=%s stage=scene error=%s", task.task_id, e)
            raise RuntimeError(f"场景生成失败: {e}") from e

    async def _step_reference_clothing_scene(
        self,
        task: Task,
        output_dir: str,
        force_floor_length: bool = False,
    ) -> Optional[str]:
        """Generate a try-on image from model + product clothing references."""
        try:
            prompt = self.wanx.build_reference_clothing_prompt(
                scene_name=task.scene,
                clothing_type=task.clothing_type,
                pose=task.pose,
                preserve_face=task.preserve_face,
                pose_mode=task.pose_mode,
                force_floor_length=force_floor_length,
                scene_prompt=task.scene_prompt,
                has_pose_reference=bool(task.pose_reference_file),
            )
            negative_prompt = build_clothing_negative_prompt(
                task.clothing_type,
                reference_mode=True,
            )
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
            logger.exception(
                "Task step failed task_id=%s stage=reference_clothing_scene error=%s",
                task.task_id,
                e,
            )
            raise RuntimeError(f"服装参考生成失败: {e}") from e

    async def _step_background(self, task: Task, output_dir: str) -> Optional[str]:
        """Generate an empty background for stable compositing."""
        try:
            return await self.wanx.generate_background(
                scene_name=task.scene,
                output_dir=output_dir,
                resolution=task.resolution,
                scene_prompt=task.scene_prompt,
                clothing_type=task.clothing_type,
            )
        except Exception as e:
            logger.exception("Task step failed task_id=%s stage=background error=%s", task.task_id, e)
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
        logger.info("Recovered interrupted processing tasks count=%s", recovered)
    _task_queue = asyncio.Queue()
    asyncio.create_task(_queue_worker())


async def enqueue_task(task_id: str):
    """提交任务到队列"""
    if _task_queue is None:
        await init_queue()
    await _task_queue.put(task_id)
    logger.info("Task enqueued task_id=%s", task_id)


async def _requeue_after_delay(task_id: str):
    delay = settings.task_retry_delay_seconds
    if delay:
        await asyncio.sleep(delay)

    task = Task.get(task_id)
    if not task:
        logger.info("Task retry skipped; not found task_id=%s", task_id)
        return
    if task.status != TaskStatus.PENDING:
        logger.info(
            "Task retry skipped; status changed task_id=%s status=%s",
            task_id,
            task.status.value,
        )
        return
    if task.retry_count > task.max_retries:
        logger.warning(
            "Task retry skipped; retry count exceeded task_id=%s retry_count=%s max_retries=%s",
            task_id,
            task.retry_count,
            task.max_retries,
        )
        return

    task.next_retry_at = ""
    task.save()
    await _task_queue.put(task_id)
    logger.info(
        "Task retry enqueued task_id=%s retry_count=%s max_retries=%s",
        task_id,
        task.retry_count,
        task.max_retries,
    )


async def _queue_worker():
    """队列消费者"""
    global _pipeline
    while True:
        task_id = await _task_queue.get()
        try:
            if _pipeline is None:
                _pipeline = TaskPipeline()
            should_retry = await _pipeline.run_task(task_id)
            if should_retry:
                asyncio.create_task(_requeue_after_delay(task_id))
        except Exception as e:
            logger.exception("Queue worker error task_id=%s error=%s", task_id, e)
            task = Task.get(task_id)
            if task:
                should_retry = _record_task_failure(task, e, stage="queue")
                if should_retry:
                    asyncio.create_task(_requeue_after_delay(task_id))
        finally:
            _task_queue.task_done()
