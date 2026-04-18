// SOURCE: https://github.com/mrdoob/three.js/issues/25936
// Reproduces z-fighting between two coplanar quads (SVG shape vs ocean plane).
// Both quads lie in the same plane at z=0; depth buffer cannot disambiguate them,
// producing an interleaved color pattern instead of a clean "shape above water".

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int vattr[] = {
    GLX_X_RENDERABLE, True,
    GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
    GLX_RENDER_TYPE,   GLX_RGBA_BIT,
    GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
    GLX_DEPTH_SIZE, 24,
    GLX_DOUBLEBUFFER, True,
    None
};

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "uniform float uZ;\n"
    "void main(){ gl_Position = vec4(aPos, uZ, 1.0); }\n";

static const char* FS =
    "#version 330 core\n"
    "uniform vec3 uColor;\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = vec4(uColor,1.0); }\n";

static GLuint compile(GLenum t, const char* src){
    GLuint s = glCreateShader(t);
    glShaderSource(s,1,&src,NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
    if(!ok){ char log[512]; glGetShaderInfoLog(s,512,NULL,log); fprintf(stderr,"shader: %s\n",log); exit(1); }
    return s;
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"XOpenDisplay failed\n"); return 1; }
    int fbcnt; GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), vattr, &fbcnt);
    if(!fbc||fbcnt==0){ fprintf(stderr,"no fbconfig\n"); return 1; }
    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0,0,512,512,0, vi->depth, InputOutput,
                               vi->visual, CWColormap|CWEventMask, &swa);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctxattr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctxattr);
    glXMakeCurrent(dpy, win, ctx);

    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(GL_VERTEX_SHADER, VS));
    glAttachShader(prog, compile(GL_FRAGMENT_SHADER, FS));
    glBindAttribLocation(prog, 0, "aPos");
    glLinkProgram(prog);

    // Water quad: full NDC extent, at z=0
    float water[] = { -1,-1,  1,-1,  1,1,  -1,-1,  1,1,  -1,1 };
    // Shape quad (smaller, centered), also at z=0 — coincident with water
    float shape[] = { -0.5f,-0.5f, 0.5f,-0.5f, 0.5f,0.5f,
                      -0.5f,-0.5f, 0.5f,0.5f,  -0.5f,0.5f };

    GLuint vao[2], vbo[2];
    glGenVertexArrays(2, vao);
    glGenBuffers(2, vbo);
    for(int i=0;i<2;i++){
        glBindVertexArray(vao[i]);
        glBindBuffer(GL_ARRAY_BUFFER, vbo[i]);
        glBufferData(GL_ARRAY_BUFFER, sizeof(water), i==0?water:shape, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,(void*)0);
    }

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glViewport(0,0,512,512);
    glClearColor(0,0,0,1);

    glUseProgram(prog);
    GLint uZ = glGetUniformLocation(prog,"uZ");
    GLint uC = glGetUniformLocation(prog,"uColor");

    for (int frame = 0; frame < 5; frame++) {
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        // Draw water at z=0 (dark teal, the ocean)
        glUniform1f(uZ, 0.0f);
        glUniform3f(uC, 0.0f, 0.12f, 0.06f);
        glBindVertexArray(vao[0]);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // Draw shape at z=0 (red, the SVG fill) — coplanar with water
        glUniform1f(uZ, 0.0f);
        glUniform3f(uC, 0.9f, 0.1f, 0.1f);
        glBindVertexArray(vao[1]);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glFinish();
        glXSwapBuffers(dpy, win);
    }

    // Capture center pixel; z-fighting makes center-quad region a speckled
    // mix rather than solid red.
    unsigned char px[3];
    glReadPixels(256, 256, 1, 1, GL_RGB, GL_UNSIGNED_BYTE, px);
    fprintf(stderr, "center pixel: %u %u %u\n", px[0], px[1], px[2]);

    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}