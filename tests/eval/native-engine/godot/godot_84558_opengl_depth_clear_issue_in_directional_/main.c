// SOURCE: https://github.com/godotengine/godot/issues/84558
// Minimal reproducer: a depth texture with GL_TEXTURE_COMPARE_MODE enabled
// remains bound to a texture unit that the active shader samples with a
// non-shadow sampler2D. This is undefined behavior per the OpenGL spec and
// triggers debug message ID 131222 on NVIDIA drivers.
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *VS =
    "#version 330 core\n"
    "const vec2 P[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3));\n"
    "out vec2 vUV;\n"
    "void main(){ vec2 p = P[gl_VertexID]; vUV = p*0.5+0.5; gl_Position = vec4(p,0,1); }\n";

// NOTE: non-shadow sampler2D bound to a depth texture with COMPARE_MODE on.
static const char *FS =
    "#version 330 core\n"
    "uniform sampler2D uTex;\n"
    "in vec2 vUV;\n"
    "out vec4 oColor;\n"
    "void main(){ oColor = vec4(texture(uTex, vUV).rrr, 1.0); }\n";

static GLuint compile(GLenum t, const char *src){
    GLuint s = glCreateShader(t);
    glShaderSource(s,1,&src,NULL); glCompileShader(s);
    GLint ok=0; glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
    if(!ok){ char log[1024]; glGetShaderInfoLog(s,1024,NULL,log); fprintf(stderr,"shader: %s\n",log); exit(1);}
    return s;
}

int main(void){
    Display *dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr,"no display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    // 1. Build the offending depth texture: depth format + COMPARE_MODE on.
    GLuint depthTex; glGenTextures(1, &depthTex);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, depthTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, 256, 256, 0,
                 GL_DEPTH_COMPONENT, GL_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_REF_TO_TEXTURE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL);

    // 2. Build a tiny shadow FBO that will hold this depth texture; clear it
    //    (the Godot "directional shadow atlas clear" pattern). The texture
    //    stays bound to unit 0 after the clear — nobody resets it.
    GLuint fbo; glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depthTex, 0);
    glDrawBuffer(GL_NONE); glReadBuffer(GL_NONE);
    glDepthMask(GL_TRUE);
    glClearDepth(1.0);
    glClear(GL_DEPTH_BUFFER_BIT);

    // 3. Switch back to the default framebuffer and draw a fullscreen tri
    //    with a non-shadow sampler2D — which still has unit 0 (depthTex with
    //    COMPARE_MODE on) bound. THIS is the undefined-behavior draw call.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0,0,256,256);
    glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT);

    GLuint prog = glCreateProgram();
    glAttachShader(prog, compile(GL_VERTEX_SHADER, VS));
    glAttachShader(prog, compile(GL_FRAGMENT_SHADER, FS));
    glLinkProgram(prog);
    glUseProgram(prog);
    glUniform1i(glGetUniformLocation(prog, "uTex"), 0);

    GLuint vao; glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}