"""Non-BCR dependencies loaded via a module extension."""

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

def _non_module_deps_impl(mctx):
    http_archive(
        name = "com_github_google_flatbuffers",
        urls = [
            "https://github.com/google/flatbuffers/archive/refs/tags/v25.2.10.tar.gz",
        ],
        strip_prefix = "flatbuffers-25.2.10",
        sha256 = "a193b5d4e811b5a857d4a61b27cb8c04bdc0c07c39f94a79b7b7c70e2c9aba94",
    )
    return mctx.extension_metadata(reproducible = True)

non_module_deps = module_extension(
    implementation = _non_module_deps_impl,
)
