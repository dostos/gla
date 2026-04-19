// SOURCE: synthetic (no upstream)
//
// Minimal OpenGL 2.1 / GLSL 120 program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3 frames.

#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#ifndef GL_TEXTURE0
#define GL_TEXTURE0 0x84C0
#endif
#ifndef GL_TEXTURE_CUBE_MAP
#define GL_TEXTURE_CUBE_MAP 0x8513
#endif
#ifndef GL_TEXTURE_CUBE_MAP_POSITIVE_X
#define GL_TEXTURE_CUBE_MAP_POSITIVE_X 0x8515
#endif
#ifndef GL_ARRAY_BUFFER
#define GL_ARRAY_BUFFER 0x8892
#endif
#ifndef GL_STATIC_DRAW
#define GL_STATIC_DRAW 0x88E4
#endif
#ifndef GL_VERTEX_SHADER
#define GL_VERTEX_SHADER 0x8B31
#endif
#ifndef GL_FRAGMENT_SHADER
#define GL_FRAGMENT_SHADER 0x8B30
#endif
#ifndef GL_COMPILE_STATUS
#define GL_COMPILE_STATUS 0x8B81
#endif
#ifndef GL_CLAMP_TO_EDGE
#define GL_CLAMP_TO_EDGE 0x812F
#endif

typedef GLuint (*fCreateShader)(GLenum);
typedef void   (*fShaderSource)(GLuint, GLsizei, const GLchar* const*, const GLint*);
typedef void   (*fCompileShader)(GLuint);
typedef void   (*fGetShaderiv)(GLuint, GLenum, GLint*);
typedef void   (*fGetShaderInfoLog)(GLuint, GLsizei, GLsizei*, GLchar*);
typedef GLuint (*fCreateProgram)(void);
typedef void   (*fAttachShader)(GLuint, GLuint);
typedef void   (*fLinkProgram)(GLuint);
typedef void   (*fUseProgram)(GLuint);
typedef void   (*fGenBuffers)(GLsizei, GLuint*);
typedef void   (*fBindBuffer)(GLenum, GLuint);
typedef void   (*fBufferData)(GLenum, long, const void*, GLenum);
typedef GLint  (*fGetAttribLocation)(GLuint, const GLchar*);
typedef void   (*fEnableVertexAttribArray)(GLuint);
typedef void   (*fVertexAttribPointer)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef GLint  (*fGetUniformLocation)(GLuint, const GLchar*);
typedef void   (*fUniform1i)(GLint, GLint);
typedef void   (*fActiveTexture)(GLenum);

#define LOAD(T, name) T name = (T)glXGetProcAddress((const GLubyte*)#name)

static const char* SKY_VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "varying vec3 vDir;\n"
    "void main() { vDir = vec3(aPos, -1.0); gl_Position = vec4(aPos, 0.999, 1.0); }\n";

static const char* SKY_FS =
    "#version 120\n"
    "uniform samplerCube uSky;\n"
    "varying vec3 vDir;\n"
    "void main() { gl_FragColor = textureCube(uSky, vDir); }\n";

static const char* TERRAIN_VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main() { gl_Position = vec4(aPos, 0.5, 1.0); }\n";

// Terrain modulates its green base color with an environment cube map
// (for neutral ambient lighting).
static const char* TERRAIN_FS =
    "#version 120\n"
    "uniform samplerCube uEnv;\n"
    "void main() {\n"
    "  vec3 base = vec3(0.1, 0.8, 0.2);\n"
    "  vec3 env = textureCube(uEnv, vec3(0.0, 1.0, 0.0)).rgb;\n"
    "  gl_FragColor = vec4(base * env * 2.0, 1.0);\n"
    "}\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
        InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(fCreateShader, glCreateShader);
    LOAD(fShaderSource, glShaderSource);
    LOAD(fCompileShader, glCompileShader);
    LOAD(fGetShaderiv, glGetShaderiv);
    LOAD(fGetShaderInfoLog, glGetShaderInfoLog);
    LOAD(fCreateProgram, glCreateProgram);
    LOAD(fAttachShader, glAttachShader);
    LOAD(fLinkProgram, glLinkProgram);
    LOAD(fUseProgram, glUseProgram);
    LOAD(fGenBuffers, glGenBuffers);
    LOAD(fBindBuffer, glBindBuffer);
    LOAD(fBufferData, glBufferData);
    LOAD(fGetAttribLocation, glGetAttribLocation);
    LOAD(fEnableVertexAttribArray, glEnableVertexAttribArray);
    LOAD(fVertexAttribPointer, glVertexAttribPointer);
    LOAD(fGetUniformLocation, glGetUniformLocation);
    LOAD(fUniform1i, glUniform1i);
    LOAD(fActiveTexture, glActiveTexture);

    #define COMPILE(stage, src) ({ \
        GLuint s = glCreateShader(stage); \
        glShaderSource(s, 1, &src, NULL); \
        glCompileShader(s); \
        GLint ok=0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok); \
        if (!ok) { char log[512]; glGetShaderInfoLog(s, 512, NULL, log); fprintf(stderr,"shader: %s\n", log); } \
        s; })
    #define MAKE_PROG(vs_src, fs_src) ({ \
        GLuint v = COMPILE(GL_VERTEX_SHADER, vs_src); \
        GLuint f = COMPILE(GL_FRAGMENT_SHADER, fs_src); \
        GLuint p = glCreateProgram(); glAttachShader(p, v); glAttachShader(p, f); glLinkProgram(p); p; })

    GLuint skyProg = MAKE_PROG(SKY_VS, SKY_FS);
    GLuint terrProg = MAKE_PROG(TERRAIN_VS, TERRAIN_FS);

    // Build two cube maps: blue sky, neutral white env probe.
    GLuint skyTex, envTex;
    glGenTextures(1, &skyTex);
    glBindTexture(GL_TEXTURE_CUBE_MAP, skyTex);
    unsigned char bluePix[3] = { 51, 77, 204 };    // (0.2, 0.3, 0.8)
    for (int i = 0; i < 6; i++)
        glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL_RGB, 1, 1, 0, GL_RGB, GL_UNSIGNED_BYTE, bluePix);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenTextures(1, &envTex);
    glBindTexture(GL_TEXTURE_CUBE_MAP, envTex);
    unsigned char whitePix[3] = { 255, 255, 255 };
    for (int i = 0; i < 6; i++)
        glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL_RGB, 1, 1, 0, GL_RGB, GL_UNSIGNED_BYTE, whitePix);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    float quad[] = { -1,-1,  1,-1,  -1,1,  1,1 };
    GLuint vbo; glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(quad), quad, GL_STATIC_DRAW);

    glViewport(0, 0, 400, 300);

    for (int frame = 0; frame < 3; frame++) {
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        // ---- skybox pass: bind sky cube map to unit 0, draw fullscreen at z=0.999
        glUseProgram(skyProg);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_CUBE_MAP, skyTex);
        glUniform1i(glGetUniformLocation(skyProg, "uSky"), 0);
        glBindBuffer(GL_ARRAY_BUFFER, vbo);
        GLint aS = glGetAttribLocation(skyProg, "aPos");
        glEnableVertexAttribArray((GLuint)aS);
        glVertexAttribPointer((GLuint)aS, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

        // ---- terrain pass.
        glUseProgram(terrProg);
        glUniform1i(glGetUniformLocation(terrProg, "uEnv"), 0);
        GLint aT = glGetAttribLocation(terrProg, "aPos");
        glEnableVertexAttribArray((GLuint)aT);
        glVertexAttribPointer((GLuint)aT, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4];
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    (void)envTex;
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XCloseDisplay(dpy);
    return 0;
}