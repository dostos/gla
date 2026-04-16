#include "src/shims/gl/shadow_state.h"
#include <assert.h>

int main(void) {
    GlaShadowState s;
    gla_shadow_state_init(&s);
    assert(s.dummy == 0);
    gla_shadow_state_reset(&s);
    return 0;
}
