// SOURCE: https://stackoverflow.com/questions/23460040/three-js-effectcomposer-browser-window-resize-issue
// Minimal reproduction of the three.js EffectComposer resize bug:
// a compositing "blend" shader keeps sampling from the *old*, smaller
// effects-pass render target after the app "resizes" and recreates its
// render targets.  The main-pass sampler is updated; the effects-pass
// sampler is not.  Result: orange (effects) sub-image looks upscaled
// while blue (main) sub-image renders correctly.

#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV = aPos*0.5 + 0.5; gl_Position = vec4(aPos,0.0,1.0); }\n";

static const char* FS_SOLID =
    "#version 330 core\n"
    "out vec4 FragColor; uniform vec3 uColor;\n"
    "void main(){ FragColor = vec4(uColor, 1.0); }\n";

static const char* FS_BLEND =
    "#version 330 core\n"
    "in vec2 vUV; out vec4 FragColor;\n"
    "uniform sampler2D tDiffuse1;\n"
    "uniform sampler2D tDiffuse2;\n"
    "void main(){ FragColor = texture(tDiffuse1, vUV) + texture(tDiffuse2, vUV); }\n";

static GLuint compile_shader(GLenum type, const char* src){
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if(!ok){ char log[1024]; glGetShaderInfoLog(s,1024,NULL,log); fprintf(stderr,"shader: %s\n",log); exit(1); }
    return s;
}

static GLuint build_program(const char* vs, const char* fs){
    GLuint v = compile_shader(GL_VERTEX_SHADER, vs);
    GLuint f = compile_shader(GL_FRAGMENT_SHADER, fs);
    GLuint p = glCreateProgram();
    glAttachShader(p,v); glAttachShader(p,f); glLinkProgram(p);
    GLint ok; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if(!ok){ char log[1024]; glGetProgramInfoLog(p,1024,NULL,log); fprintf(stderr,"link: %s\n",log); exit(1); }
    return p;
}

static void make_render_target(GLuint* fbo, GLuint* tex, int w, int h){
    glGenTextures(1, tex);
    glBindTexture(GL_TEXTURE_2D, *tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, *fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, *tex, 0);
}

static void render_solid(GLuint prog, GLuint vao, GLuint fbo, int w, int h,
                         float r, float g, float b){
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glViewport(0, 0, w, h);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glUniform3f(glGetUniformLocation(prog, "uColor"), r, g, b);
    glBindVertexArray(vao);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attr);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen),
                                    vi->visual, AllocNone);
    XSetWindowAttributes swa; swa.colormap = cmap; swa.event_mask = 0;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen),
                               0, 0, 800, 600, 0, vi->depth, InputOutput,
                               vi->visual, CWColormap | CWEventMask, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // Fullscreen quad VAO.
    float quad[] = { -1.f,-1.f,  1.f,-1.f,  -1.f,1.f,  1.f,1.f };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    GLuint solid = build_program(VS, FS_SOLID);
    GLuint blend = build_program(VS, FS_BLEND);

    // === Initial small window: app renders at 200x150. ===
    int W1 = 200, H1 = 150;
    GLuint mainFboOld, mainTexOld, fxFboOld, fxTexOld;
    make_render_target(&mainFboOld, &mainTexOld, W1, H1);
    make_render_target(&fxFboOld,   &fxTexOld,   W1, H1);

    render_solid(solid, vao, mainFboOld, W1, H1, 0.0f, 0.0f, 1.0f); // blue main pass
    render_solid(solid, vao, fxFboOld,   W1, H1, 1.0f, 0.5f, 0.0f); // orange effects pass

    // Bind blend sampler uniforms to texture units 0 and 1.
    glUseProgram(blend);
    glUniform1i(glGetUniformLocation(blend, "tDiffuse1"), 0);
    glUniform1i(glGetUniformLocation(blend, "tDiffuse2"), 1);

    // === "Resize" to 800x600 ===
    // Recreate both render targets (mimics EffectComposer.reset()).
    int W2 = 800, H2 = 600;
    GLuint mainFbo, mainTex, fxFbo, fxTex;
    make_render_target(&mainFbo, &mainTex, W2, H2);
    make_render_target(&fxFbo,   &fxTex,   W2, H2);
    render_solid(solid, vao, mainFbo, W2, H2, 0.0f, 0.0f, 1.0f);
    render_solid(solid, vao, fxFbo,   W2, H2, 1.0f, 0.5f, 0.0f);

    // Composite to default framebuffer at the NEW size.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W2, H2);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(blend);

    // Main sampler is updated to the new render target...
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, mainTex);

    // ...but the effects sampler is left pointing at the OLD 200x150 texture.
    // This mirrors the bug: blend.uniforms.tDiffuse2.value was never
    // reassigned to effects.renderTarget2 after reset().
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, fxTexOld);

    glBindVertexArray(vao);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, NULL, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}