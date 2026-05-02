// SOURCE: https://github.com/pmndrs/postprocessing/issues/735
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(location=1) in vec2 aUV;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV=aUV; gl_Position=vec4(aPos,0,1); }\n";

// EffectPass fragment: samples the post-processed scene texture and writes
// it with alpha = uOpacity.  In v6.38.1 the EffectMaterial was switched to
// NormalBlending + transparent=true, so this alpha then feeds the GL blend
// stage instead of being discarded.
static const char* FS =
    "#version 330 core\n"
    "in vec2 vUV;\n"
    "uniform sampler2D uTex;\n"
    "uniform float uOpacity;\n"
    "out vec4 FragColor;\n"
    "void main(){ vec4 c = texture(uTex, vUV); FragColor = vec4(c.rgb, uOpacity); }\n";

static GLuint compile(GLenum k, const char* s){
    GLuint sh = glCreateShader(k);
    glShaderSource(sh, 1, &s, NULL); glCompileShader(sh);
    return sh;
}

static void xerr_noop(Display* d, XErrorEvent* e){ (void)d; (void)e; }

int main(void){
    XSetErrorHandler(xerr_noop);
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "no display\n"); return 1; }

    int fbattr[] = {
        GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_DOUBLEBUFFER, True,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24, None
    };
    int nfb;
    GLXFBConfig* fbs = glXChooseFBConfig(dpy, DefaultScreen(dpy), fbattr, &nfb);
    if(!fbs || nfb<1){ fprintf(stderr, "no fbconfig\n"); return 1; }
    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbs[0]);
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddress(
            (const GLubyte*)"glXCreateContextAttribsARB");
    int ctxattr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbs[0], 0, True, ctxattr);
    glXMakeCurrent(dpy, win, ctx);

    float quad[] = {
        -1,-1, 0,0,   1,-1, 1,0,  -1, 1, 0,1,
         1,-1, 1,0,   1, 1, 1,1,  -1, 1, 0,1,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float), (void*)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float),
        (void*)(2*sizeof(float)));
    glEnableVertexAttribArray(1);

    // Post-processed scene result: solid bright orange (255,153,51).  This
    // stands in for the output of a prior EffectPass (e.g. bloom) that
    // EffectPass is now asked to copy to the default framebuffer.
    unsigned char pixels[4*4*4];
    for(int i=0;i<16;i++){
        pixels[i*4+0]=255; pixels[i*4+1]=153; pixels[i*4+2]=51; pixels[i*4+3]=255;
    }
    GLuint tex;
    glGenTextures(1, &tex); glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 4, 4, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs); glAttachShader(prog, fs); glLinkProgram(prog);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "uTex"), 0);
    // Mid-animation opacity sample: fade halfway.  With the v6.38.1 blend
    // state this alpha will be consumed by GL blending instead of passing
    // through as a copy.
    glUniform1f(glGetUniformLocation(prog, "uOpacity"), 0.5f);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, 256, 256);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // EffectPass v6.38.1 final-pass blend state: NormalBlending with
    // transparent=true on the default framebuffer.
    glEnable(GL_BLEND);
    glBlendEquation(GL_FUNC_ADD);
    glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                        GL_ONE,       GL_ONE_MINUS_SRC_ALPHA);

    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, 0, 0);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}