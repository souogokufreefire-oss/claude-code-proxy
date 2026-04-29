"""FastAPI route handlers."""

from fastapi import APIRouter, Depends, Request, Response

from config.settings import Settings
from core.anthropic import get_token_count

from . import dependencies
from .dependencies import get_settings, require_api_key
from .model_router import ModelRouter
from .models.anthropic import MessagesRequest, TokenCountRequest
from .models.responses import ModelResponse, ModelsListResponse
from .services import ClaudeProxyService

router = APIRouter()


SUPPORTED_CLAUDE_MODELS = [
    ModelResponse(
        id="claude-opus-4-20250514",
        display_name="Claude Opus 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-sonnet-4-20250514",
        display_name="Claude Sonnet 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-haiku-4-20250514",
        display_name="Claude Haiku 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-opus-20240229",
        display_name="Claude 3 Opus",
        created_at="2024-02-29T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        created_at="2024-10-22T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        created_at="2024-03-07T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku",
        created_at="2024-10-22T00:00:00Z",
    ),
]


def get_proxy_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ClaudeProxyService:
    """Build the request service for route handlers."""
    model_override = dependencies.request_model_override(request, settings)
    return ClaudeProxyService(
        settings,
        provider_getter=lambda provider_type: dependencies.resolve_provider(
            provider_type, app=request.app, settings=settings
        ),
        model_router=ModelRouter(settings, request_model_override=model_override),
        token_counter=get_token_count,
    )


def _probe_response(allow: str) -> Response:
    """Return an empty success response for compatibility probes."""
    return Response(status_code=204, headers={"Allow": allow})


# =============================================================================
# Routes
# =============================================================================
@router.post("/v1/messages")
async def create_message(
    request_data: MessagesRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Create a message (always streaming)."""
    return service.create_message(request_data)


@router.api_route("/v1/messages", methods=["HEAD", "OPTIONS"])
async def probe_messages(_auth=Depends(require_api_key)):
    """Respond to Claude compatibility probes for the messages endpoint."""
    return _probe_response("POST, HEAD, OPTIONS")


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request_data: TokenCountRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Count tokens for a request."""
    return service.count_tokens(request_data)


@router.api_route("/v1/messages/count_tokens", methods=["HEAD", "OPTIONS"])
async def probe_count_tokens(_auth=Depends(require_api_key)):
    """Respond to Claude compatibility probes for the token count endpoint."""
    return _probe_response("POST, HEAD, OPTIONS")


@router.get("/")
async def root(
    settings: Settings = Depends(get_settings), _auth=Depends(require_api_key)
):
    """Root endpoint."""
    return {
        "status": "ok",
        "provider": settings.provider_type,
        "model": settings.model,
    }


@router.api_route("/", methods=["HEAD", "OPTIONS"])
async def probe_root(_auth=Depends(require_api_key)):
    """Respond to compatibility probes for the root endpoint."""
    return _probe_response("GET, HEAD, OPTIONS")


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.api_route("/health", methods=["HEAD", "OPTIONS"])
async def probe_health():
    """Respond to compatibility probes for the health endpoint."""
    return _probe_response("GET, HEAD, OPTIONS")


@router.get("/v1/models", response_model=ModelsListResponse)
async def list_models(_auth=Depends(require_api_key)):
    """List the Claude model ids this proxy advertises for compatibility."""
    return ModelsListResponse(
        data=SUPPORTED_CLAUDE_MODELS,
        first_id=SUPPORTED_CLAUDE_MODELS[0].id if SUPPORTED_CLAUDE_MODELS else None,
        has_more=False,
        last_id=SUPPORTED_CLAUDE_MODELS[-1].id if SUPPORTED_CLAUDE_MODELS else None,
    )
