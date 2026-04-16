#include <gtest/gtest.h>
#include "src/core/query/query_engine.h"

TEST(QueryEngineTest, Execute) {
    gla::query::QueryEngine qe;
    EXPECT_EQ(qe.execute("SELECT 1"), 0);
}
