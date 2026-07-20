"""Pydantic models for LinkedIn Corp MCP Server tools."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class BaseToolResponse(BaseModel):
    success: bool
    error: Optional[dict] = None


class ProfileResponse(BaseToolResponse):
    profile: Optional[Dict[str, Any]] = None


class OrganizationListResponse(BaseToolResponse):
    organizations: Optional[List[Dict[str, Any]]] = None


class OrganizationResponse(BaseToolResponse):
    organization: Optional[Dict[str, Any]] = None


class CreatePostResponse(BaseToolResponse):
    post_id: Optional[str] = None
    post_urn: Optional[str] = None
    organization_urn: Optional[str] = None
    visibility: Optional[str] = None
    message: Optional[str] = None
    dry_run: bool = False
    request_body: Optional[Dict[str, Any]] = None


class PostResponse(BaseToolResponse):
    post: Optional[Dict[str, Any]] = None


class ActionResponse(BaseToolResponse):
    post_urn: Optional[str] = None
    message: Optional[str] = None
