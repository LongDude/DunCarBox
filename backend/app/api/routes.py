from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.schemas.errors import ErrorResponse
from app.schemas.packing import BoxTypeSchema, PackingRequestSchema, PackingResultSchema
from app.services.fixtures import DemoFixtures
from app.services.packing import PackingService
from app.services.packing_jobs import PackingJobs
from app.storage.boxes import BoxRepository

router = APIRouter(
    prefix="/api/v1",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
ResourceId = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]


def get_repository(request: Request) -> BoxRepository:
    return request.app.state.box_repository


def get_packing_service(request: Request) -> PackingService:
    return request.app.state.packing_service


def get_fixtures(request: Request) -> DemoFixtures:
    return request.app.state.demo_fixtures


def get_jobs(request: Request) -> PackingJobs:
    return request.app.state.packing_jobs


class PackingJobResponse(BaseModel):
    id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    error: str | None
    elapsed_seconds: float
    timeout_seconds: float | None
    stage: str = "preparing"
    progress: float | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    api_version: Literal["v1"] = "v1"
    engine: str


class DemoScenarioResponse(BaseModel):
    id: str
    name: str
    description: str
    expected_status: Literal["success", "partial", "impossible"]


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health(request: Request) -> HealthResponse:
    return HealthResponse(engine=request.app.state.engine_version)


@router.get("/boxes", response_model=list[BoxTypeSchema], tags=["boxes"])
def list_boxes(
    repository: Annotated[BoxRepository, Depends(get_repository)],
) -> list[BoxTypeSchema]:
    return [BoxTypeSchema.model_validate(box) for box in repository.list()]


@router.post("/boxes", response_model=BoxTypeSchema, status_code=201, tags=["boxes"])
def create_box(
    box: BoxTypeSchema,
    repository: Annotated[BoxRepository, Depends(get_repository)],
) -> BoxTypeSchema:
    return BoxTypeSchema.model_validate(repository.create(box.to_domain()))


@router.put("/boxes/{box_id}", response_model=BoxTypeSchema, tags=["boxes"])
def update_box(
    box_id: ResourceId,
    box: BoxTypeSchema,
    repository: Annotated[BoxRepository, Depends(get_repository)],
) -> BoxTypeSchema:
    if box_id != box.id:
        raise HTTPException(422, "id в URL и теле запроса должны совпадать.")
    return BoxTypeSchema.model_validate(repository.update(box.to_domain()))


@router.delete("/boxes/{box_id}", status_code=204, tags=["boxes"])
def delete_box(
    box_id: ResourceId,
    repository: Annotated[BoxRepository, Depends(get_repository)],
) -> Response:
    repository.delete(box_id)
    return Response(status_code=204)


@router.post(
    "/pack",
    response_model=PackingResultSchema,
    tags=["packing"],
)
def pack(
    payload: PackingRequestSchema,
    service: Annotated[PackingService, Depends(get_packing_service)],
) -> PackingResultSchema:
    return PackingResultSchema.model_validate(service.pack(payload.to_domain()))


@router.get("/demo/scenarios", response_model=list[DemoScenarioResponse], tags=["demo"])
def demo_scenarios(fixtures: Annotated[DemoFixtures, Depends(get_fixtures)]) -> list[dict]:
    return fixtures.scenarios


@router.post("/pack/jobs", response_model=PackingJobResponse, status_code=202, tags=["packing"])
def start_job(
    payload: PackingRequestSchema,
    jobs: Annotated[PackingJobs, Depends(get_jobs)],
) -> dict:
    return jobs.submit(payload.to_domain())


@router.get("/pack/jobs/{job_id}", response_model=PackingJobResponse, tags=["packing"])
def job_status(job_id: ResourceId, jobs: Annotated[PackingJobs, Depends(get_jobs)]) -> dict:
    return jobs.status(job_id)


@router.get("/pack/jobs/{job_id}/result", response_class=FileResponse, tags=["packing"])
def job_result(job_id: ResourceId, jobs: Annotated[PackingJobs, Depends(get_jobs)]) -> FileResponse:
    return FileResponse(jobs.result_path(job_id), media_type="application/json")


@router.delete("/pack/jobs/{job_id}", status_code=204, tags=["packing"])
def cancel_job(job_id: ResourceId, jobs: Annotated[PackingJobs, Depends(get_jobs)]) -> Response:
    jobs.cancel(job_id)
    return Response(status_code=204)


@router.get("/demo/scenarios/{scenario_id}", response_model=PackingRequestSchema, tags=["demo"])
def demo_request(
    scenario_id: ResourceId,
    fixtures: Annotated[DemoFixtures, Depends(get_fixtures)],
) -> PackingRequestSchema:
    result = fixtures.request(scenario_id)
    if result is None:
        raise HTTPException(404, "Демонстрационный сценарий не найден.")
    return result
