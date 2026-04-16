#ifndef GLA_SHADOW_STATE_H
#define GLA_SHADOW_STATE_H

typedef struct GlaShadowState {
    int dummy;
} GlaShadowState;

void gla_shadow_state_init(GlaShadowState *s);
void gla_shadow_state_reset(GlaShadowState *s);

#endif // GLA_SHADOW_STATE_H
