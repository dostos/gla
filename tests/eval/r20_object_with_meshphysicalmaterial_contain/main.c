// SOURCE: https://github.com/mrdoob/three.js/issues/25648
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static Display *dpy;
static Window  win;
static GLXContext ctx;

#define W 512
#define H 512

typedef void (*PFNGLGENFRAMEBUFFERS)(GLsizei,GLuint*);
typedef void (*PFNGLBINDFRAMEBUFFER)(GLenum,GLuint);
typedef void (*PFNGLFRAMEBUFFERTEXTURE2D)(GLenum,GLenum,GLenum,GLuint,GLint);
typedef void (*PFNGLGENERATEMIPMAP)(GLenum);
typedef GLuint (*PFNGLCREATESHADER)(GLenum);
typedef void (*PFNGLSHADERSOURCE)(GLuint,GLsizei,const char* const*,const GLint*);
typedef void (*PFNGLCOMPILESHADER)(GLuint);
typedef GLuint (*PFNGLCREATEPROGRAM)(void);
typedef void (*PFNGLATTACHSHADER)(GLuint,GLuint);
typedef void (*PFNGLLINKPROGRAM)(GLuint);
typedef void (*PFNGLUSEPROGRAM)(GLuint);
typedef GLint (*PFNGLGETUNIFORMLOCATION)(GLuint,const char*);
typedef void (*PFNGLUNIFORM1F)(GLint,GLfloat);
typedef void (*PFNGLUNIFORM2F)(GLint,GLfloat,GLfloat);
typedef void (*PFNGLUNIFORM1I)(GLint,GLint);
typedef void (*PFNGLGENVERTEXARRAYS)(GLsizei,GLuint*);
typedef void (*PFNGLBINDVERTEXARRAY)(GLuint);
typedef void (*PFNGLGENBUFFERS)(GLsizei,GLuint*);
typedef void (*PFNGLBINDBUFFER)(GLenum,GLuint);
typedef void (*PFNGLBUFFERDATA)(GLenum,GLsizeiptr,const void*,GLenum);
typedef void (*PFNGLENABLEVERTEXATTRIBARRAY)(GLuint);
typedef void (*PFNGLVERTEXATTRIBPOINTER)(GLuint,GLint,GLenum,GLboolean,GLsizei,const void*);

static PFNGLGENFRAMEBUFFERS glGenFramebuffers;
static PFNGLBINDFRAMEBUFFER glBindFramebuffer;
static PFNGLFRAMEBUFFERTEXTURE2D glFramebufferTexture2D;
static PFNGLGENERATEMIPMAP glGenerateMipmap;
static PFNGLCREATESHADER glCreateShader;
static PFNGLSHADERSOURCE glShaderSource;
static PFNGLCOMPILESHADER glCompileShader;
static PFNGLCREATEPROGRAM glCreateProgram;
static PFNGLATTACHSHADER glAttachShader;
static PFNGLLINKPROGRAM glLinkProgram;
static PFNGLUSEPROGRAM glUseProgram;
static PFNGLGETUNIFORMLOCATION glGetUniformLocation;
static PFNGLUNIFORM1F glUniform1f;
static PFNGLUNIFORM2F glUniform2f;
static PFNGLUNIFORM1I glUniform1i;
static PFNGLGENVERTEXARRAYS glGenVertexArrays;
static PFNGLBINDVERTEXARRAY glBindVertexArray;
static PFNGLGENBUFFERS glGenBuffers;
static PFNGLBINDBUFFER glBindBuffer;
static PFNGLBUFFERDATA glBufferData;
static PFNGLENABLEVERTEXATTRIBARRAY glEnableVertexAttribArray;
static PFNGLVERTEXATTRIBPOINTER glVertexAttribPointer;

#define GL_FRAMEBUFFER 0x8D40
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_VERTEX_SHADER 0x8B31

static void *gl_get(const char *n) {
    return (void*)glXGetProcAddressARB((const GLubyte*)n);
}

static const char *vs =
"#version 330 core\n"
"layout(location=0) in vec2 a;\n"
"out vec2 vUv;\n"
"void main(){ vUv = a*0.5+0.5; gl_Position = vec4(a,0,1);}\n";

static const char *bg_fs =
"#version 330 core\n"
"in vec2 vUv; out vec4 o;\n"
"void main(){ o = vec4(vUv.x, 1.0-vUv.y, 0.25, 1.0);}\n";

static const char *trans_fs =
"#version 330 core\n"
"in vec2 vUv; out vec4 o;\n"
"uniform sampler2D tex;\n"
"uniform float lod;\n"
"vec4 cubic(float v){\n"
"  vec4 n = vec4(1.0,2.0,3.0,4.0) - v;\n"
"  vec4 s = n*n*n;\n"
"  float x=s.x; float y=s.y-4.0*s.x;\n"
"  float z=s.z-4.0*s.y+6.0*s.x;\n"
"  float w=6.0-x-y-z;\n"
"  return vec4(x,y,z,w)*(1.0/6.0);\n"
"}\n"
"vec4 bicubic(sampler2D t, vec2 uv, float l){\n"
"  vec2 sz = vec2(textureSize(t,int(l)));\n"
"  vec2 inv = 1.0/sz;\n"
"  uv = uv*sz - 0.5;\n"
"  vec2 fuv = fract(uv);\n"
"  uv -= fuv;\n"
"  vec4 cx = cubic(fuv.x);\n"
"  vec4 cy = cubic(fuv.y);\n"
"  vec4 c = uv.xxyy + vec2(-0.5,1.5).xyxy;\n"
"  vec4 s = vec4(cx.xz+cx.yw, cy.xz+cy.yw);\n"
"  vec4 off = c + vec4(cx.yw,cy.yw)/s;\n"
"  off *= vec4(inv,inv);\n"
"  vec4 a = textureLod(t, off.xz, l);\n"
"  vec4 b = textureLod(t, off.yz, l);\n"
"  vec4 d = textureLod(t, off.xw, l);\n"
"  vec4 e = textureLod(t, off.yw, l);\n"
"  float sx = s.x/(s.x+s.y);\n"
"  float sy = s.z/(s.z+s.w);\n"
"  return mix(mix(e,d,sx), mix(b,a,sx), sy);\n"
"}\n"
"void main(){\n"
"  vec4 lo = bicubic(tex, vUv, floor(lod));\n"
"  vec4 hi = bicubic(tex, vUv, ceil(lod));\n"
"  o = mix(lo, hi, fract(lod));\n"
"}\n";

static GLuint mk_shader(GLenum t, const char *src){
    GLuint s = glCreateShader(t);
    glShaderSource(s,1,&src,NULL); glCompileShader(s);
    return s;
}
static GLuint mk_prog(const char *vsrc, const char *fsrc){
    GLuint p = glCreateProgram();
    glAttachShader(p, mk_shader(GL_VERTEX_SHADER, vsrc));
    glAttachShader(p, mk_shader(GL_FRAGMENT_SHADER, fsrc));
    glLinkProgram(p);
    return p;
}

int main(void){
    dpy = XOpenDisplay(NULL);
    int attrs[] = {GLX_RGBA, GLX_DEPTH_SIZE,24, GLX_DOUBLEBUFFER, None};
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy,vi->screen), vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    win = XCreateWindow(dpy, RootWindow(dpy,vi->screen), 0,0,W,H,0,vi->depth,InputOutput,vi->visual,CWColormap|CWEventMask,&swa);
    XMapWindow(dpy, win);
    ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glGenFramebuffers = gl_get("glGenFramebuffers");
    glBindFramebuffer = gl_get("glBindFramebuffer");
    glFramebufferTexture2D = gl_get("glFramebufferTexture2D");
    glGenerateMipmap = gl_get("glGenerateMipmap");
    glCreateShader = gl_get("glCreateShader");
    glShaderSource = gl_get("glShaderSource");
    glCompileShader = gl_get("glCompileShader");
    glCreateProgram = gl_get("glCreateProgram");
    glAttachShader = gl_get("glAttachShader");
    glLinkProgram = gl_get("glLinkProgram");
    glUseProgram = gl_get("glUseProgram");
    glGetUniformLocation = gl_get("glGetUniformLocation");
    glUniform1f = gl_get("glUniform1f");
    glUniform2f = gl_get("glUniform2f");
    glUniform1i = gl_get("glUniform1i");
    glGenVertexArrays = gl_get("glGenVertexArrays");
    glBindVertexArray = gl_get("glBindVertexArray");
    glGenBuffers = gl_get("glGenBuffers");
    glBindBuffer = gl_get("glBindBuffer");
    glBufferData = gl_get("glBufferData");
    glEnableVertexAttribArray = gl_get("glEnableVertexAttribArray");
    glVertexAttribPointer = gl_get("glVertexAttribPointer");

    float quad[] = {-1,-1, 1,-1, -1,1, 1,1};
    GLuint vao, vbo;
    glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,NULL);

    GLuint fbo, fboTex;
    glGenTextures(1,&fboTex);
    glBindTexture(GL_TEXTURE_2D, fboTex);
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,W,H,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, 0x2703);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glGenFramebuffers(1,&fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, fboTex, 0);

    GLuint bg = mk_prog(vs, bg_fs);
    GLuint tr = mk_prog(vs, trans_fs);

    glViewport(0,0,W,H);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(bg);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    glBindTexture(GL_TEXTURE_2D, fboTex);
    glGenerateMipmap(GL_TEXTURE_2D);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glClearColor(0.1,0.1,0.1,1); glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(tr);
    glUniform1i(glGetUniformLocation(tr,"tex"), 0);
    glUniform1f(glGetUniformLocation(tr,"lod"), 3.0f);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

    unsigned char px[4];
    glReadPixels(W/2,H/2,1,1,GL_RGBA,GL_UNSIGNED_BYTE,px);
    printf("center rgba=%u,%u,%u,%u\n",px[0],px[1],px[2],px[3]);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}