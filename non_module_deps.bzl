"""Non-BCR dependencies loaded via a module extension."""

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def _non_module_deps_impl(mctx):
    http_archive(
        name = "com_github_google_flatbuffers",
        urls = [
            "https://github.com/google/flatbuffers/archive/refs/tags/v25.2.10.tar.gz",
        ],
        strip_prefix = "flatbuffers-25.2.10",
        sha256 = "b9c2df49707c57a48fc0923d52b8c73beb72d675f9d44b2211e4569be40a7421",
    )
    return mctx.extension_metadata(reproducible = True)

non_module_deps = module_extension(
    implementation = _non_module_deps_impl,
)
