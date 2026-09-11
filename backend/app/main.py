from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import router
from app.config import Settings
from app.domain.interfaces import PackingEngine
from app.packing.stub import DemoPackingEngine
from app.services.fixtures import DemoFixtures
from app.services.packing import PackingService
from app.storage.boxes import PostgresBoxRepository


def create_app(settings: Settings | None = None, engine: PackingEngine | None = None) -> FastAPI:
    configuration = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        fixtures = DemoFixtures(configuration.demo_dir)
        repository = PostgresBoxRepository(configuration.database_url)
        repository.initialize(fixtures.catalog)
        selected_engine = engine if engine is not None else DemoPackingEngine(fixtures.pairs)
        application.state.box_repository = repository
        application.state.demo_fixtures = fixtures
        application.state.packing_service = PackingService(selected_engine)
        application.state.engine_version = getattr(selected_engine, "version", "custom")
        yield

    application = FastAPI(
        title="DunCarBox",
        version="0.1.0",
        lifespan=lifespan,
        description="Foundation API. Packing currently replays fixed demo scenarios.",
    )
    register_error_handlers(application)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    application.include_router(router)
    return application


app = create_app()
