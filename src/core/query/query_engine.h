#pragma once

namespace gla::query {

class QueryEngine {
public:
    QueryEngine() = default;
    ~QueryEngine() = default;
    int execute(const char *query);
};

} // namespace gla::query
