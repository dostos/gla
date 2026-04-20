// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/1679
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef GLuint (*PFNCREATESHADER)(GLenum);
typedef void (*PFNSHADERSOURCE)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFNCOMPILESHADER)(GLuint);
typedef GLuint (*PFNCREATEPROGRAM)(void);
typedef void (*PFNATTACHSHADER)(GLuint, GLuint);
typedef void (*PFNLINKPROGRAM)(GLuint);
typedef void (*PFNUSEPROGRAM)(GLuint);
typedef void (*PFNGENVAOS)(GLsizei, GLuint*);
typedef void (*PFNBINDVAO)(GLuint);
typedef void (*PFNGENBUFFERS)(GLsizei, GLuint*);
typedef void (*PFNBINDBUFFER)(GLenum, GLuint);
typedef void (*PFNBUFFERDATA)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFNVERTEXATTRIB)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNENABLEVA)(GLuint);
typedef GLint (*PFNGETUNIFORMLOC)(GLuint, const char*);
typedef void (*PFNUNIFORM4F)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);

#define GLG(T,N,S) T N = (T)glXGetProcAddress((const GLubyte*)S)

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

static const char* FS =
"#version 330 core\n"
"uniform vec4 u_color;\n"
"out vec4 o;\n"
"void main(){ o = u_color; }\n";

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int scr = DefaultScreen(dpy);
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER,
                    GLX_RED_SIZE,8, GLX_GREEN_SIZE,8, GLX_BLUE_SIZE,8,
                    GLX_DEPTH_SIZE,24, GLX_STENCIL_SIZE,8, None };
    XVisualInfo* vi = glXChooseVisual(dpy, scr, attrs);
    if(!vi){ fprintf(stderr,"no visual\n"); return 1; }
    Window root = RootWindow(dpy, scr);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, win, ctx);

    GLG(PFNCREATESHADER, glCreateShader_, "glCreateShader");
    GLG(PFNSHADERSOURCE, glShaderSource_, "glShaderSource");
    GLG(PFNCOMPILESHADER, glCompileShader_, "glCompileShader");
    GLG(PFNCREATEPROGRAM, glCreateProgram_, "glCreateProgram");
    GLG(PFNATTACHSHADER, glAttachShader_, "glAttachShader");
    GLG(PFNLINKPROGRAM, glLinkProgram_, "glLinkProgram");
    GLG(PFNUSEPROGRAM, glUseProgram_, "glUseProgram");
    GLG(PFNGENVAOS, glGenVertexArrays_, "glGenVertexArrays");
    GLG(PFNBINDVAO, glBindVertexArray_, "glBindVertexArray");
    GLG(PFNGENBUFFERS, glGenBuffers_, "glGenBuffers");
    GLG(PFNBINDBUFFER, glBindBuffer_, "glBindBuffer");
    GLG(PFNBUFFERDATA, glBufferData_, "glBufferData");
    GLG(PFNVERTEXATTRIB, glVertexAttribPointer_, "glVertexAttribPointer");
    GLG(PFNENABLEVA, glEnableVertexAttribArray_, "glEnableVertexAttribArray");
    GLG(PFNGETUNIFORMLOC, glGetUniformLocation_, "glGetUniformLocation");
    GLG(PFNUNIFORM4F, glUniform4f_, "glUniform4f");

    GLuint vs = glCreateShader_(GL_VERTEX_SHADER);
    glShaderSource_(vs,1,&VS,NULL); glCompileShader_(vs);
    GLuint fs = glCreateShader_(GL_FRAGMENT_SHADER);
    glShaderSource_(fs,1,&FS,NULL); glCompileShader_(fs);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog,vs); glAttachShader_(prog,fs); glLinkProgram_(prog);
    glUseProgram_(prog);

    GLuint vao; glGenVertexArrays_(1,&vao); glBindVertexArray_(vao);
    GLuint vbo; glGenBuffers_(1,&vbo); glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glVertexAttribPointer_(0,2,GL_FLOAT,GL_FALSE,2*sizeof(float),(void*)0);
    glEnableVertexAttribArray_(0);
    GLint u_color = glGetUniformLocation_(prog, "u_color");

    glViewport(0,0,256,256);
    glClearColor(0,0,0,1);
    glClearStencil(0);
    glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);

    /* Tile regions in NDC. */
    float tile_a[] = { -1.0f, 0.0f,  0.0f, 0.0f, -1.0f, 1.0f,  0.0f, 1.0f };
    float tile_b[] = {  0.0f,-1.0f,  1.0f,-1.0f, 0.0f, 0.0f,  1.0f, 0.0f };
    /* Content geometries. */
    float green_quad[] = { -0.7f, 0.3f, -0.3f, 0.3f, -0.7f, 0.7f, -0.3f, 0.7f };
    float fullscreen[]  = { -1.0f,-1.0f,  1.0f,-1.0f, -1.0f, 1.0f,  1.0f, 1.0f };

    /* Phase 1: write per-tile clip IDs into stencil (high 5 bits). */
    glEnable(GL_STENCIL_TEST);
    glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
    glStencilMask(0xF8);
    glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
    glUniform4f_(u_color, 0.0f, 0.0f, 0.0f, 0.0f);

    int id_a = 1;
    glStencilFunc(GL_ALWAYS, id_a << 3, 0xF8);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(tile_a), tile_a, GL_STATIC_DRAW);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    int id_b = 33;
    glStencilFunc(GL_ALWAYS, id_b << 3, 0xF8);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(tile_b), tile_b, GL_STATIC_DRAW);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    /* Phase 2: draw tile contents gated by stencil EQUAL. */
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glStencilMask(0x00);
    glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);

    glStencilFunc(GL_EQUAL, id_a << 3, 0xF8);
    glUniform4f_(u_color, 0.0f, 1.0f, 0.0f, 1.0f);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(green_quad), green_quad, GL_STATIC_DRAW);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glStencilFunc(GL_EQUAL, id_b << 3, 0xF8);
    glUniform4f_(u_color, 1.0f, 0.0f, 0.0f, 1.0f);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(fullscreen), fullscreen, GL_STATIC_DRAW);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glXSwapBuffers(dpy, win);

    /* Sample a point inside tile A's region, outside the green content. */
    unsigned char px[4] = {0};
    glReadPixels(16, 240, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("tile-A outer pixel rgba=%u,%u,%u,%u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}