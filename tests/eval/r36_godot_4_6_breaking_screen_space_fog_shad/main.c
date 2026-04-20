// SOURCE: https://github.com/godotengine/godot/issues/116040
//
// Minimal screen-space fog quad pattern: a fullscreen triangle whose fragment
// shader samples a depth-like gradient and blends a fog color based on view
// direction. This mirrors the "screen space fog shader on a quad mesh"
// construct that Sky3D's AtmFog.gdshader uses on top of the sky pass.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void (*PFN_GENV)(GLsizei, GLuint*);
typedef void (*PFN_BINDV)(GLuint);
typedef void (*PFN_GENB)(GLsizei, GLuint*);
typedef void (*PFN_BINDB)(GLenum, GLuint);
typedef void (*PFN_BUFD)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void (*PFN_VATTR)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void (*PFN_EATTR)(GLuint);
typedef GLuint (*PFN_CSH)(GLenum);
typedef void (*PFN_SHSRC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void (*PFN_CSHC)(GLuint);
typedef GLuint (*PFN_CPR)(void);
typedef void (*PFN_ATSH)(GLuint, GLuint);
typedef void (*PFN_LPR)(GLuint);
typedef void (*PFN_UPR)(GLuint);
typedef GLint (*PFN_GUL)(GLuint, const char*);
typedef void (*PFN_U2F)(GLint, GLfloat, GLfloat);

#define GL_ARRAY_BUFFER 0x8892
#define GL_STATIC_DRAW 0x88E4
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30

static void* gl(const char* n){return (void*)glXGetProcAddressARB((const GLubyte*)n);}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){fprintf(stderr,"no display\n");return 1;}
    int scr = DefaultScreen(dpy);
    int fbattr[] = {GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None};
    XVisualInfo* vi = glXChooseVisual(dpy, scr, fbattr);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy,scr), vi->visual, AllocNone);
    XSetWindowAttributes swa = {.colormap=cmap, .event_mask=ExposureMask};
    Window win = XCreateWindow(dpy, RootWindow(dpy,scr), 0,0, 800,600, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    PFN_GENV  glGenVertexArrays = gl("glGenVertexArrays");
    PFN_BINDV glBindVertexArray = gl("glBindVertexArray");
    PFN_GENB  glGenBuffers      = gl("glGenBuffers");
    PFN_BINDB glBindBuffer      = gl("glBindBuffer");
    PFN_BUFD  glBufferData      = gl("glBufferData");
    PFN_VATTR glVertexAttribPointer = gl("glVertexAttribPointer");
    PFN_EATTR glEnableVertexAttribArray = gl("glEnableVertexAttribArray");
    PFN_CSH   glCreateShader    = gl("glCreateShader");
    PFN_SHSRC glShaderSource    = gl("glShaderSource");
    PFN_CSHC  glCompileShader   = gl("glCompileShader");
    PFN_CPR   glCreateProgram   = gl("glCreateProgram");
    PFN_ATSH  glAttachShader    = gl("glAttachShader");
    PFN_LPR   glLinkProgram     = gl("glLinkProgram");
    PFN_UPR   glUseProgram      = gl("glUseProgram");
    PFN_GUL   glGetUniformLocation = gl("glGetUniformLocation");
    PFN_U2F   glUniform2f       = gl("glUniform2f");

    const char* vs =
        "#version 330 core\n"
        "layout(location=0) in vec2 p;\n"
        "out vec2 v_uv;\n"
        "void main(){ v_uv = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";
    const char* fs =
        "#version 330 core\n"
        "in vec2 v_uv;\n"
        "uniform vec2 u_view_dir;\n"
        "out vec4 frag;\n"
        "void main(){\n"
        "  float sky = clamp(v_uv.y, 0.0, 1.0);\n"
        "  float fog = smoothstep(0.3, 0.9, sky + u_view_dir.y);\n"
        "  vec3 base = mix(vec3(0.25,0.55,0.95), vec3(0.85,0.75,0.60), sky);\n"
        "  vec3 fogc = vec3(0.8,0.7,0.55);\n"
        "  frag = vec4(mix(base, fogc, fog), 1.0);\n"
        "}\n";

    GLuint v = glCreateShader(GL_VERTEX_SHADER);
    glShaderSource(v,1,&vs,NULL); glCompileShader(v);
    GLuint f = glCreateShader(GL_FRAGMENT_SHADER);
    glShaderSource(f,1,&fs,NULL); glCompileShader(f);
    GLuint prog = glCreateProgram();
    glAttachShader(prog,v); glAttachShader(prog,f); glLinkProgram(prog);

    float quad[] = {-1,-1, 3,-1, -1,3};
    GLuint vao,vbo;
    glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,sizeof(quad),quad,GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,2*sizeof(float),(void*)0);
    glEnableVertexAttribArray(0);

    glViewport(0,0,800,600);
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT);
    glUseProgram(prog);
    glUniform2f(glGetUniformLocation(prog,"u_view_dir"), 0.0f, 0.4f);
    glDrawArrays(GL_TRIANGLES,0,3);
    glXSwapBuffers(dpy,win);

    unsigned char px[4];
    glReadPixels(400,150,1,1,GL_RGBA,GL_UNSIGNED_BYTE,px);
    printf("upper center rgba=%u,%u,%u,%u\n",px[0],px[1],px[2],px[3]);
    glReadPixels(400,450,1,1,GL_RGBA,GL_UNSIGNED_BYTE,px);
    printf("lower center rgba=%u,%u,%u,%u\n",px[0],px[1],px[2],px[3]);

    glXMakeCurrent(dpy,None,NULL);
    glXDestroyContext(dpy,ctx);
    XDestroyWindow(dpy,win);
    XCloseDisplay(dpy);
    return 0;
}