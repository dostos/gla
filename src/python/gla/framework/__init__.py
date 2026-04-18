"""OpenGPA framework integration package.

Provides types and storage for framework plugins to supply scene graph metadata
alongside captured GPU frames.
"""
from .types import (
    FrameMetadata,
    FrameworkMaterial,
    FrameworkObject,
    FrameworkRenderPass,
    MaterialInfo,
    ObjectInfo,
    PixelExplanation,
    RenderPassInfo,
)
from .metadata_store import MetadataStore
from .debug_groups import DebugGroupNode, build_debug_group_tree
from . import correlation
from .query_engine import FrameworkQueryEngine

__all__ = [
    "FrameMetadata",
    "FrameworkMaterial",
    "FrameworkObject",
    "FrameworkRenderPass",
    "MaterialInfo",
    "MetadataStore",
    "ObjectInfo",
    "PixelExplanation",
    "RenderPassInfo",
    "DebugGroupNode",
    "build_debug_group_tree",
    "correlation",
    "FrameworkQueryEngine",
]
