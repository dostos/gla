// SOURCE: https://github.com/godotengine/godot/issues/116038
// Pattern: full-screen QuadMesh used as a screen-space fog pass samples the
// depth buffer, while a separate volumetric-fog pass also reads/writes depth.
// This minimal repro sets up the same shape: draw scene geometry (fills depth),
// render a full-screen quad whose fragment shader samples the depth texture,
// and sample with a depth-range transform that depends on camera pitch.
// The real Godot bug manifests only inside the engine's volumetric-fog +
// QuadMesh interaction; see upstream_snapshot for the relevant files.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef void (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFNGLGENVERTEXARRAYSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDVERTEXARRAYPROC)(GLuint);
typedef void (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void (*PFNGLGENFRAMEBUFFERSPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDFRAMEBUFFERPROC)(GLenum, GLuint);
typedef void (*PFNGLFRAMEBUFFERTEXTURE2DPROC)(GLenum, GLenum, GLenum, GLuint, GLint);
typedef GLint (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void (*PFNGLUNIFORM1IPROC)(GLint, GLint);
typedef void (*PFNGLUNIFORM1FPROC)(GLint, GLfloat);
typedef void (*PFNGLACTIVETEXTUREPROC)(GLenum);

#define LOAD(T,n) T n = (T)glXGetProcAddressARB((const GLubyte*)#n)

static const char* VS_SCENE =
"#version 330 core\n"
"layout(location=0) in vec3 p;\n"
"uniform float pitch;\n"
"void main(){\n"
"  vec3 q = p;\n"
"  q.z -= 2.0 + pitch*0.001;\n"
"  gl_Position = vec4(q.xy, q.z*0.1, 1.0);\n"
"}\n";

static const char* FS_SCENE =
"#version 330 core\n"
"out vec4 o;\n"
"void main(){ o = vec4(0.6,0.7,0.9,1.0); }\n";

static const char* VS_QUAD =
"#version 330 core\n"
"layout(location=0) in vec2 p;\n"
"out vec2 uv;\n"
"void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0.0,1.0); }\n";

static const char* FS_FOG =
"#version 330 core\n"
"in vec2 uv;\n"
"out vec4 o;\n"
"uniform sampler2D depthTex;\n"
"uniform float pitch;\n"
"void main(){\n"
"  float d = texture(depthTex, uv).r;\n"
"  // Simulate the screen-space fog pass that combines a pitch-dependent\n"
"  // transform with depth sample — corrupts when sign flips across screen.\n"
"  float sky = step(0.99999, d);\n"
"  float fog = clamp((d - 0.5)*pitch*4.0, 0.0, 1.0);\n"
"  o = vec4(mix(vec3(0.2,0.4,0.8), vec3(1.0), fog), 1.0) * (1.0-sky) + sky*vec4(0);\n"
"}\n";

static GLuint make_prog(const char* vs, const char* fs,
    PFNGLCREATESHADERPROC cs, PFNGLSHADERSOURCEPROC ss, PFNGLCOMPILESHADERPROC cp,
    PFNGLCREATEPROGRAMPROC cpr, PFNGLATTACHSHADERPROC at, PFNGLLINKPROGRAMPROC lp){
    GLuint v=cs(GL_VERTEX_SHADER); ss(v,1,&vs,NULL); cp(v);
    GLuint f=cs(GL_FRAGMENT_SHADER); ss(f,1,&fs,NULL); cp(f);
    GLuint p=cpr(); at(p,v); at(p,f); lp(p); return p;
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){fprintf(stderr,"no display\n"); return 1;}
    int fbattrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, fbattrs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa; swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0,0, 800,600, 0, vi->depth, InputOutput, vi->visual, CWColormap, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(PFNGLCREATESHADERPROC, glCreateShader);
    LOAD(PFNGLSHADERSOURCEPROC, glShaderSource);
    LOAD(PFNGLCOMPILESHADERPROC, glCompileShader);
    LOAD(PFNGLCREATEPROGRAMPROC, glCreateProgram);
    LOAD(PFNGLATTACHSHADERPROC, glAttachShader);
    LOAD(PFNGLLINKPROGRAMPROC, glLinkProgram);
    LOAD(PFNGLUSEPROGRAMPROC, glUseProgram);
    LOAD(PFNGLGENBUFFERSPROC, glGenBuffers);
    LOAD(PFNGLBINDBUFFERPROC, glBindBuffer);
    LOAD(PFNGLBUFFERDATAPROC, glBufferData);
    LOAD(PFNGLGENVERTEXARRAYSPROC, glGenVertexArrays);
    LOAD(PFNGLBINDVERTEXARRAYPROC, glBindVertexArray);
    LOAD(PFNGLVERTEXATTRIBPOINTERPROC, glVertexAttribPointer);
    LOAD(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    LOAD(PFNGLGENFRAMEBUFFERSPROC, glGenFramebuffers);
    LOAD(PFNGLBINDFRAMEBUFFERPROC, glBindFramebuffer);
    LOAD(PFNGLFRAMEBUFFERTEXTURE2DPROC, glFramebufferTexture2D);
    LOAD(PFNGLGETUNIFORMLOCATIONPROC, glGetUniformLocation);
    LOAD(PFNGLUNIFORM1IPROC, glUniform1i);
    LOAD(PFNGLUNIFORM1FPROC, glUniform1f);
    LOAD(PFNGLACTIVETEXTUREPROC, glActiveTexture);

    GLuint fbo; glGenFramebuffers(1,&fbo); glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    GLuint color; glGenTextures(1,&color); glBindTexture(GL_TEXTURE_2D, color);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,800,600,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color, 0);
    GLuint depth; glGenTextures(1,&depth); glBindTexture(GL_TEXTURE_2D, depth);
    glTexImage2D(GL_TEXTURE_2D,0,GL_DEPTH_COMPONENT24,800,600,0,GL_DEPTH_COMPONENT,GL_FLOAT,NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depth, 0);

    GLuint scene = make_prog(VS_SCENE, FS_SCENE, glCreateShader, glShaderSource, glCompileShader, glCreateProgram, glAttachShader, glLinkProgram);
    GLuint fog   = make_prog(VS_QUAD,  FS_FOG,   glCreateShader, glShaderSource, glCompileShader, glCreateProgram, glAttachShader, glLinkProgram);

    float tri[] = { -0.8f,-0.8f,0.f,  0.8f,-0.8f,0.f,  0.f,0.8f,0.f };
    float quad[] = { -1,-1, 1,-1, -1,1, 1,1 };
    GLuint vbo_t, vao_t; glGenVertexArrays(1,&vao_t); glGenBuffers(1,&vbo_t);
    glBindVertexArray(vao_t); glBindBuffer(GL_ARRAY_BUFFER, vbo_t);
    glBufferData(GL_ARRAY_BUFFER, sizeof(tri), tri, GL_STATIC_DRAW);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,0,0); glEnableVertexAttribArray(0);
    GLuint vbo_q, vao_q; glGenVertexArrays(1,&vao_q); glGenBuffers(1,&vbo_q);
    glBindVertexArray(vao_q); glBindBuffer(GL_ARRAY_BUFFER, vbo_q);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,0); glEnableVertexAttribArray(0);

    glViewport(0,0,800,600);
    glEnable(GL_DEPTH_TEST);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
    glUseProgram(scene);
    glUniform1f(glGetUniformLocation(scene,"pitch"), 45.0f);
    glBindVertexArray(vao_t); glDrawArrays(GL_TRIANGLES,0,3);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glDisable(GL_DEPTH_TEST);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(fog);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, depth);
    glUniform1i(glGetUniformLocation(fog,"depthTex"), 0);
    glUniform1f(glGetUniformLocation(fog,"pitch"), 1.5f);
    glBindVertexArray(vao_q); glDrawArrays(GL_TRIANGLE_STRIP,0,4);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}