// SOURCE: https://github.com/qgis/qwc2/issues/532
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef GL_FRAMEBUFFER
#define GL_FRAMEBUFFER 0x8D40
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_FRAMEBUFFER_COMPLETE 0x8CD5
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_TEXTURE0 0x84C0
#endif

typedef void (*PFN_GLGENFRAMEBUFFERS)(GLsizei, GLuint*);
typedef void (*PFN_GLBINDFRAMEBUFFER)(GLenum, GLuint);
typedef void (*PFN_GLFRAMEBUFFERTEXTURE2D)(GLenum, GLenum, GLenum, GLuint, GLint);
typedef GLenum (*PFN_GLCHECKFRAMEBUFFERSTATUS)(GLenum);
typedef GLuint (*PFN_GLCREATESHADER)(GLenum);
typedef void (*PFN_GLSHADERSOURCE)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFN_GLCOMPILESHADER)(GLuint);
typedef GLuint (*PFN_GLCREATEPROGRAM)(void);
typedef void (*PFN_GLATTACHSHADER)(GLuint, GLuint);
typedef void (*PFN_GLLINKPROGRAM)(GLuint);
typedef void (*PFN_GLUSEPROGRAM)(GLuint);
typedef void (*PFN_GLGENVERTEXARRAYS)(GLsizei, GLuint*);
typedef void (*PFN_GLBINDVERTEXARRAY)(GLuint);
typedef void (*PFN_GLGENBUFFERS)(GLsizei, GLuint*);
typedef void (*PFN_GLBINDBUFFER)(GLenum, GLuint);
typedef void (*PFN_GLBUFFERDATA)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFN_GLVERTEXATTRIBPOINTER)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFN_GLENABLEVERTEXATTRIBARRAY)(GLuint);
typedef GLint (*PFN_GLGETUNIFORMLOCATION)(GLuint, const char*);
typedef void (*PFN_GLUNIFORM1I)(GLint, GLint);
typedef void (*PFN_GLACTIVETEXTURE)(GLenum);

#define GET(name, type) type name = (type)glXGetProcAddressARB((const GLubyte*)#name)

static const char* vs_src =
    "#version 330 core\n"
    "layout(location=0) in vec2 a_pos;\n"
    "out vec2 v_uv;\n"
    "void main(){ v_uv = a_pos*0.5+0.5; gl_Position = vec4(a_pos,0,1); }\n";

static const char* fs_src =
    "#version 330 core\n"
    "in vec2 v_uv;\n"
    "uniform sampler2D u_tex;\n"
    "out vec4 frag;\n"
    "void main(){ frag = texture(u_tex, v_uv) + vec4(0.02,0.0,0.0,1.0); }\n";

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int scr = DefaultScreen(dpy);
    int attr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, scr, attr);
    Window root = RootWindow(dpy, scr);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0,0,256,256,0, vi->depth, InputOutput,
                               vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    GET(glGenFramebuffers, PFN_GLGENFRAMEBUFFERS);
    GET(glBindFramebuffer, PFN_GLBINDFRAMEBUFFER);
    GET(glFramebufferTexture2D, PFN_GLFRAMEBUFFERTEXTURE2D);
    GET(glCheckFramebufferStatus, PFN_GLCHECKFRAMEBUFFERSTATUS);
    GET(glCreateShader, PFN_GLCREATESHADER);
    GET(glShaderSource, PFN_GLSHADERSOURCE);
    GET(glCompileShader, PFN_GLCOMPILESHADER);
    GET(glCreateProgram, PFN_GLCREATEPROGRAM);
    GET(glAttachShader, PFN_GLATTACHSHADER);
    GET(glLinkProgram, PFN_GLLINKPROGRAM);
    GET(glUseProgram, PFN_GLUSEPROGRAM);
    GET(glGenVertexArrays, PFN_GLGENVERTEXARRAYS);
    GET(glBindVertexArray, PFN_GLBINDVERTEXARRAY);
    GET(glGenBuffers, PFN_GLGENBUFFERS);
    GET(glBindBuffer, PFN_GLBINDBUFFER);
    GET(glBufferData, PFN_GLBUFFERDATA);
    GET(glVertexAttribPointer, PFN_GLVERTEXATTRIBPOINTER);
    GET(glEnableVertexAttribArray, PFN_GLENABLEVERTEXATTRIBARRAY);
    GET(glGetUniformLocation, PFN_GLGETUNIFORMLOCATION);
    GET(glUniform1i, PFN_GLUNIFORM1I);
    GET(glActiveTexture, PFN_GLACTIVETEXTURE);

    // offscreen color target for 3D scene
    GLuint tex;
    glGenTextures(1,&tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 256,256,0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    GLuint fbo;
    glGenFramebuffers(1,&fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    if(glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE){
        fprintf(stderr,"fbo incomplete\n"); return 1;
    }

    // seed the render target with a non-black color
    glViewport(0,0,256,256);
    glClearColor(0.2f, 0.5f, 0.9f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    GLuint vs = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(vs,1,&vs_src,NULL); glCompileShader(vs);
    GLuint fs = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(fs,1,&fs_src,NULL); glCompileShader(fs);
    GLuint prog = glCreateProgram();
    glAttachShader(prog,vs); glAttachShader(prog,fs); glLinkProgram(prog);

    float quad[] = { -1,-1,  1,-1,  -1,1,  1,1 };
    GLuint vao, vbo;
    glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,NULL);
    glEnableVertexAttribArray(0);

    glUseProgram(prog);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glUniform1i(glGetUniformLocation(prog, "u_tex"), 0);

    // render pass into fbo
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glViewport(0,0,256,256);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    // present to default framebuffer
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0,0,256,256);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(128,128,1,1,GL_RGBA,GL_UNSIGNED_BYTE,px);
    printf("default-fb center pixel rgba=%d,%d,%d,%d\n", px[0],px[1],px[2],px[3]);

    GLenum err = glGetError();
    printf("glGetError=0x%04x\n", err);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}