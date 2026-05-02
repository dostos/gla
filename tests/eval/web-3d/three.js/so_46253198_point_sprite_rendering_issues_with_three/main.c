// SOURCE: https://stackoverflow.com/questions/46253198/point-sprite-rendering-issues-with-three-js
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define W 800
#define H 600
#define N_POINTS 4000

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static const char* VS =
"#version 330 core\n"
"layout(location=0) in vec3 aPos;\n"
"uniform mat4 uMVP;\n"
"void main(){ gl_Position = uMVP * vec4(aPos,1.0); gl_PointSize = 18.0; }\n";

static const char* FS =
"#version 330 core\n"
"out vec4 oColor;\n"
"void main(){\n"
"  vec2 d = gl_PointCoord - vec2(0.5);\n"
"  float r = length(d);\n"
"  // Soft circle with alpha fringe (no discard).\n"
"  float a = 1.0 - smoothstep(0.40, 0.50, r);\n"
"  oColor = vec4(1.0, 0.55, 0.15, a);\n"
"}\n";

typedef GLuint (*PFN_glCreateShader)(GLenum);
typedef void (*PFN_glShaderSource)(GLuint,GLsizei,const GLchar*const*,const GLint*);
typedef void (*PFN_glCompileShader)(GLuint);
typedef void (*PFN_glGetShaderiv)(GLuint,GLenum,GLint*);
typedef void (*PFN_glGetShaderInfoLog)(GLuint,GLsizei,GLsizei*,GLchar*);
typedef GLuint (*PFN_glCreateProgram)(void);
typedef void (*PFN_glAttachShader)(GLuint,GLuint);
typedef void (*PFN_glLinkProgram)(GLuint);
typedef void (*PFN_glUseProgram)(GLuint);
typedef void (*PFN_glGenBuffers)(GLsizei,GLuint*);
typedef void (*PFN_glBindBuffer)(GLenum,GLuint);
typedef void (*PFN_glBufferData)(GLenum,GLsizeiptr,const void*,GLenum);
typedef void (*PFN_glGenVertexArrays)(GLsizei,GLuint*);
typedef void (*PFN_glBindVertexArray)(GLuint);
typedef void (*PFN_glVertexAttribPointer)(GLuint,GLint,GLenum,GLboolean,GLsizei,const void*);
typedef void (*PFN_glEnableVertexAttribArray)(GLuint);
typedef GLint (*PFN_glGetUniformLocation)(GLuint,const GLchar*);
typedef void (*PFN_glUniformMatrix4fv)(GLint,GLsizei,GLboolean,const GLfloat*);

#define L(T,N) static PFN_##N N; N = (PFN_##N)glXGetProcAddressARB((const GLubyte*)#N)

static GLuint mkprog(void){
    L(,glCreateShader); L(,glShaderSource); L(,glCompileShader);
    L(,glGetShaderiv); L(,glGetShaderInfoLog);
    L(,glCreateProgram); L(,glAttachShader); L(,glLinkProgram);
    GLuint v=glCreateShader(GL_VERTEX_SHADER); glShaderSource(v,1,&VS,NULL); glCompileShader(v);
    GLuint f=glCreateShader(GL_FRAGMENT_SHADER); glShaderSource(f,1,&FS,NULL); glCompileShader(f);
    GLuint p=glCreateProgram(); glAttachShader(p,v); glAttachShader(p,f); glLinkProgram(p);
    return p;
}

static void mvp_topdown(float* m, float cx, float cy, float cz){
    // Simple top-down orthographic-ish perspective: perspective * lookAt(top).
    // Hand-rolled to avoid GLM. Projects a Y=1 plane into view space.
    float n=1.0f, fa=2000.0f, fov=45.0f*(float)M_PI/180.0f;
    float a=(float)W/(float)H, t=tanf(fov*0.5f);
    float p00=1.0f/(a*t), p11=1.0f/t, p22=-(fa+n)/(fa-n), p23=-2.0f*fa*n/(fa-n);
    // View: camera at (0, cy, 0) looking down -Y, up=+Z.
    // Rows of view matrix:
    // right = (1,0,0), up_ws = (0,0,-1) (we pick so up_screen = +Z world),
    // forward = (0,-1,0). translation = -cam.
    (void)cx;(void)cz;
    float V[16] = {
        1,0,0,0,
        0,0,-1,0,
        0,-1,0,0,
        0,0,0,1
    };
    V[12] = 0; V[13] = 0; V[14] = -cy; // translate by -camera
    float P[16] = {
        p00,0,0,0,
        0,p11,0,0,
        0,0,p22,-1,
        0,0,p23,0
    };
    for(int r=0;r<4;r++) for(int c=0;c<4;c++){
        float s=0.0f;
        for(int k=0;k<4;k++) s += P[r+k*4]*V[k+c*4];
        m[r+c*4]=s;
    }
}

int main(void){
    Display* dpy=XOpenDisplay(NULL); if(!dpy){fprintf(stderr,"no display\n");return 1;}
    int vis_attribs[]={GLX_X_RENDERABLE,True,GLX_DRAWABLE_TYPE,GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,GLX_RGBA_BIT,GLX_RED_SIZE,8,GLX_GREEN_SIZE,8,
        GLX_BLUE_SIZE,8,GLX_ALPHA_SIZE,8,GLX_DEPTH_SIZE,24,GLX_DOUBLEBUFFER,True,0};
    int fbc_n=0; GLXFBConfig* fbc=glXChooseFBConfig(dpy,DefaultScreen(dpy),vis_attribs,&fbc_n);
    XVisualInfo* vi=glXGetVisualFromFBConfig(dpy,fbc[0]);
    XSetWindowAttributes swa={0};
    swa.colormap=XCreateColormap(dpy,RootWindow(dpy,vi->screen),vi->visual,AllocNone);
    swa.event_mask=StructureNotifyMask;
    Window win=XCreateWindow(dpy,RootWindow(dpy,vi->screen),0,0,W,H,0,vi->depth,InputOutput,vi->visual,CWColormap|CWEventMask,&swa);
    XMapWindow(dpy,win);
    int ctx_attribs[]={GLX_CONTEXT_MAJOR_VERSION_ARB,3,GLX_CONTEXT_MINOR_VERSION_ARB,3,
        GLX_CONTEXT_PROFILE_MASK_ARB,GLX_CONTEXT_CORE_PROFILE_BIT_ARB,0};
    glXCreateContextAttribsARBProc cca=(glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    GLXContext ctx=cca(dpy,fbc[0],NULL,True,ctx_attribs);
    glXMakeCurrent(dpy,win,ctx);

    L(,glGenBuffers); L(,glBindBuffer); L(,glBufferData);
    L(,glGenVertexArrays); L(,glBindVertexArray);
    L(,glVertexAttribPointer); L(,glEnableVertexAttribArray);
    L(,glUseProgram); L(,glGetUniformLocation); L(,glUniformMatrix4fv);

    // Lay out N_POINTS on a grid at Y=1.
    float* pos = (float*)malloc(sizeof(float)*3*N_POINTS);
    int side = (int)sqrtf((float)N_POINTS);
    for(int i=0;i<N_POINTS;i++){
        int ix=i%side, iz=i/side;
        pos[3*i+0] = ((float)ix/(float)side - 0.5f) * 180.0f;
        pos[3*i+1] = 1.0f;                 // all points coplanar
        pos[3*i+2] = ((float)iz/(float)side - 0.5f) * 180.0f;
    }

    GLuint vao,vbo;
    glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,sizeof(float)*3*N_POINTS,pos,GL_STATIC_DRAW);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,3*sizeof(float),(void*)0);
    glEnableVertexAttribArray(0);

    GLuint prog=mkprog(); glUseProgram(prog);
    glEnable(GL_PROGRAM_POINT_SIZE);

    glEnable(GL_DEPTH_TEST);
    glDepthMask(GL_TRUE);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    glClearColor(0.11f,0.14f,0.18f,1.0f);
    glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);

    float MVP[16]; mvp_topdown(MVP, 0, 300.0f, 0);
    GLint uloc=glGetUniformLocation(prog,"uMVP");
    glUniformMatrix4fv(uloc,1,GL_FALSE,MVP);

    glDrawArrays(GL_POINTS,0,N_POINTS);
    glXSwapBuffers(dpy,win);

    free(pos);
    return 0;
}