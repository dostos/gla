// SOURCE: https://github.com/godotengine/godot/issues/9913
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
typedef void (*PFNBUFFERSUBDATA)(GLenum, GLintptr, GLsizeiptr, const void*);
typedef void (*PFNVERTEXATTRIB)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNENABLEVA)(GLuint);
typedef void (*PFNVERTEXATTRIBDIV)(GLuint, GLuint);
typedef void (*PFNDRAWARRAYSINST)(GLenum, GLint, GLsizei, GLsizei);
typedef GLint (*PFNGETUNIFORMLOC)(GLuint, const char*);
typedef void (*PFNUNIFORM2F)(GLint, GLfloat, GLfloat);

#define GLG(T,N,S) T N = (T)glXGetProcAddress((const GLubyte*)S)

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec2 a_pos;\n"
"layout(location=1) in vec4 a_xform;\n" /* xy = translate, zw = scale */
"layout(location=2) in vec3 a_color;\n"
"uniform vec2 u_viewport;\n"
"out vec3 v_color;\n"
"void main(){\n"
"  vec2 p = a_pos * a_xform.zw + a_xform.xy;\n"
"  gl_Position = vec4(p / u_viewport * 2.0 - 1.0, 0.0, 1.0);\n"
"  v_color = a_color;\n"
"}\n";

static const char* FS =
"#version 330 core\n"
"in vec3 v_color;\n"
"out vec4 o;\n"
"void main(){ o = vec4(v_color, 1.0); }\n";

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int scr = DefaultScreen(dpy);
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, scr, attrs);
    Window root = RootWindow(dpy, scr);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window w = XCreateWindow(dpy, root, 0, 0, 400, 400, 0, vi->depth,
                             InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, w);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, w, ctx);

    GLG(PFNCREATESHADER,glCreateShader_,"glCreateShader");
    GLG(PFNSHADERSOURCE,glShaderSource_,"glShaderSource");
    GLG(PFNCOMPILESHADER,glCompileShader_,"glCompileShader");
    GLG(PFNCREATEPROGRAM,glCreateProgram_,"glCreateProgram");
    GLG(PFNATTACHSHADER,glAttachShader_,"glAttachShader");
    GLG(PFNLINKPROGRAM,glLinkProgram_,"glLinkProgram");
    GLG(PFNUSEPROGRAM,glUseProgram_,"glUseProgram");
    GLG(PFNGENVAOS,glGenVertexArrays_,"glGenVertexArrays");
    GLG(PFNBINDVAO,glBindVertexArray_,"glBindVertexArray");
    GLG(PFNGENBUFFERS,glGenBuffers_,"glGenBuffers");
    GLG(PFNBINDBUFFER,glBindBuffer_,"glBindBuffer");
    GLG(PFNBUFFERDATA,glBufferData_,"glBufferData");
    GLG(PFNBUFFERSUBDATA,glBufferSubData_,"glBufferSubData");
    GLG(PFNVERTEXATTRIB,glVertexAttribPointer_,"glVertexAttribPointer");
    GLG(PFNENABLEVA,glEnableVertexAttribArray_,"glEnableVertexAttribArray");
    GLG(PFNVERTEXATTRIBDIV,glVertexAttribDivisor_,"glVertexAttribDivisor");
    GLG(PFNDRAWARRAYSINST,glDrawArraysInstanced_,"glDrawArraysInstanced");
    GLG(PFNGETUNIFORMLOC,glGetUniformLocation_,"glGetUniformLocation");
    GLG(PFNUNIFORM2F,glUniform2f_,"glUniform2f");

    GLuint vs = glCreateShader_(GL_VERTEX_SHADER);
    glShaderSource_(vs,1,&VS,NULL); glCompileShader_(vs);
    GLuint fs = glCreateShader_(GL_FRAGMENT_SHADER);
    glShaderSource_(fs,1,&FS,NULL); glCompileShader_(fs);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog,vs); glAttachShader_(prog,fs); glLinkProgram_(prog);

    GLuint vao; glGenVertexArrays_(1,&vao); glBindVertexArray_(vao);

    /* Per-vertex quad geometry (64x64 tile). */
    float quad[] = { 0,0, 64,0, 0,64, 0,64, 64,0, 64,64 };
    GLuint vbo; glGenBuffers_(1,&vbo); glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer_(0,2,GL_FLOAT,GL_FALSE,2*sizeof(float),(void*)0);
    glEnableVertexAttribArray_(0);

    /* Quadrant instance buffer: 4 tiles in one batch.
       Port of the pattern from Godot's canvas_item renderer: batched
       transforms streamed into a single VBO, then drawn in one call. */
    /*                  tx     ty     sx    sy    r    g    b         */
    float inst_good[] = {
         16.0f,  16.0f, 1.0f, 1.0f, 0.2f, 0.8f, 0.2f,
        112.0f,  16.0f, 1.0f, 1.0f, 0.2f, 0.8f, 0.2f,
        208.0f,  16.0f, 1.0f, 1.0f, 0.2f, 0.8f, 0.2f,
        304.0f,  16.0f, 1.0f, 1.0f, 0.2f, 0.8f, 0.2f,
    };
    float stale_xform[] = { 900.0f, 900.0f, 1.0f, 1.0f };

    GLuint ibo; glGenBuffers_(1,&ibo); glBindBuffer_(GL_ARRAY_BUFFER, ibo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(inst_good), inst_good, GL_DYNAMIC_DRAW);
    glBufferSubData_(GL_ARRAY_BUFFER, 2*7*sizeof(float), 4*sizeof(float), stale_xform);

    glVertexAttribPointer_(1,4,GL_FLOAT,GL_FALSE,7*sizeof(float),(void*)0);
    glEnableVertexAttribArray_(1); glVertexAttribDivisor_(1,1);
    glVertexAttribPointer_(2,3,GL_FLOAT,GL_FALSE,7*sizeof(float),(void*)(4*sizeof(float)));
    glEnableVertexAttribArray_(2); glVertexAttribDivisor_(2,1);

    glViewport(0,0,400,400);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram_(prog);
    glUniform2f_(glGetUniformLocation_(prog,"u_viewport"), 400.0f, 400.0f);
    glDrawArraysInstanced_(GL_TRIANGLES, 0, 6, 4);

    glXSwapBuffers(dpy, w);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, w);
    XCloseDisplay(dpy);
    return 0;
}