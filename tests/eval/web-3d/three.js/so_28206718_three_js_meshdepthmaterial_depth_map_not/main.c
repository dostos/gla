// SOURCE: https://stackoverflow.com/questions/28206718/three-js-meshdepthmaterial-depth-map-not-uniformly-distributed
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

static int vis_attribs[] = {
    GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None
};

static const char* vs_src =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform mat4 uProj;\n"
    "uniform mat4 uView;\n"
    "uniform mat4 uModel;\n"
    "void main(){ gl_Position = uProj * uView * uModel * vec4(aPos,1.0); }\n";

// Visualize non-linear window-space depth (gl_FragCoord.z) as grayscale.
// This mirrors what a naive depth-material does when reading the depth buffer.
static const char* fs_src =
    "#version 330 core\n"
    "out vec4 FragColor;\n"
    "void main(){ float d = gl_FragCoord.z; FragColor = vec4(d,d,d,1.0); }\n";

static GLuint compile(GLenum t, const char* s){
    GLuint sh = glCreateShader(t);
    glShaderSource(sh,1,&s,NULL); glCompileShader(sh);
    GLint ok=0; glGetShaderiv(sh,GL_COMPILE_STATUS,&ok);
    if(!ok){ char log[1024]; glGetShaderInfoLog(sh,1024,NULL,log); fprintf(stderr,"shader: %s\n",log); exit(1);}
    return sh;
}

static void mat4_identity(float* m){ memset(m,0,64); m[0]=m[5]=m[10]=m[15]=1.0f; }
static void mat4_translate(float* m, float x, float y, float z){
    mat4_identity(m); m[12]=x; m[13]=y; m[14]=z;
}
// Standard GL perspective: looking down -Z.
static void mat4_perspective(float* m, float fovy, float aspect, float n, float f){
    float t = 1.0f/tanf(fovy*0.5f);
    memset(m,0,64);
    m[0]=t/aspect; m[5]=t;
    m[10] = (f+n)/(n-f);
    m[11] = -1.0f;
    m[14] = (2.0f*f*n)/(n-f);
}

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    XVisualInfo* vi = glXChooseVisual(dpy, 0, vis_attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0,0, 512,512, 0, vi->depth, InputOutput,
                               vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // Quad geometry in local space, spanning z=0 plane.
    float verts[] = {
        -10,-10,0,  10,-10,0,  10,10,0,
        -10,-10,0,  10,10,0,  -10,10,0,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glGenBuffers(1,&vbo); glBindBuffer(GL_ARRAY_BUFFER,vbo);
    glBufferData(GL_ARRAY_BUFFER,sizeof(verts),verts,GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,0,(void*)0);

    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(GL_VERTEX_SHADER, vs_src));
    glAttachShader(prog, compile(GL_FRAGMENT_SHADER, fs_src));
    glLinkProgram(prog);
    glUseProgram(prog);

    // Camera far from origin with tight near/far (mirrors the Stack Overflow case).
    // camera.position.z = 600, near = 550, far = 650.
    // Objects placed at z = 0, -15, -30, -45 (world). All inside frustum.
    float proj[16], view[16], model[16];
    mat4_perspective(proj, 60.0f*3.14159f/180.0f, 1.0f, 550.0f, 650.0f);
    mat4_translate(view, 0, 0, -600.0f); // move world so camera sits at z=+600 looking -z

    glUniformMatrix4fv(glGetUniformLocation(prog,"uProj"),1,GL_FALSE,proj);
    glUniformMatrix4fv(glGetUniformLocation(prog,"uView"),1,GL_FALSE,view);

    glEnable(GL_DEPTH_TEST);
    glClearColor(0,0,0,1);
    glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);

    // Four quads spread across the frustum's world-space depth range.
    float z_positions[4] = { 0.0f, -15.0f, -30.0f, -45.0f };
    float x_offsets[4]   = { -30.0f, -10.0f, 10.0f, 30.0f };
    for(int i=0;i<4;i++){
        mat4_translate(model, x_offsets[i], 0, z_positions[i]);
        glUniformMatrix4fv(glGetUniformLocation(prog,"uModel"),1,GL_FALSE,model);
        glDrawArrays(GL_TRIANGLES,0,6);
    }

    glXSwapBuffers(dpy, win);
    glFinish();
    return 0;
}