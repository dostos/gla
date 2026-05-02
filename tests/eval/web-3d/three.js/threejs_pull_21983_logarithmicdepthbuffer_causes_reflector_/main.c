// SOURCE: https://github.com/mrdoob/three.js/issues/21980
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const int W = 256, H = 256;

static GLuint compile_shader(GLenum kind, const char* src){
    GLuint s = glCreateShader(kind);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if(!ok){
        char log[1024]; glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return s;
}

static GLuint link_program(const char* vsrc, const char* fsrc){
    GLuint vs = compile_shader(GL_VERTEX_SHADER, vsrc);
    GLuint fs = compile_shader(GL_FRAGMENT_SHADER, fsrc);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    GLint ok = 0; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if(!ok){
        char log[1024]; glGetProgramInfoLog(p, sizeof log, NULL, log);
        fprintf(stderr, "link failed: %s\n", log);
        exit(1);
    }
    glDeleteShader(vs); glDeleteShader(fs);
    return p;
}

static void mat_perspective(float* m, float fovy_deg, float aspect, float zn, float zf){
    float f = 1.0f / tanf(fovy_deg * 0.5f * 3.14159265f / 180.0f);
    memset(m, 0, 16 * sizeof(float));
    m[0]  = f / aspect;
    m[5]  = f;
    m[10] = (zf + zn) / (zn - zf);
    m[11] = -1.0f;
    m[14] = (2.0f * zf * zn) / (zn - zf);
}

static void mat_translate_z(float* m, float tz){
    memset(m, 0, 16 * sizeof(float));
    m[0] = m[5] = m[10] = m[15] = 1.0f;
    m[14] = tz;
}

static void mat_mul(float* M, const float* A, const float* B){
    float r[16];
    for(int c=0;c<4;c++) for(int rr=0;rr<4;rr++){
        float s=0; for(int k=0;k<4;k++) s += A[k*4+rr] * B[c*4+k];
        r[c*4+rr] = s;
    }
    memcpy(M, r, sizeof r);
}

// World geometry shader: uses logarithmic depth output.
static const char* VS_WORLD =
"#version 330 core\n"
"layout(location=0) in vec3 a_pos;\n"
"uniform mat4 u_mvp;\n"
"out float v_fragDepth;\n"
"void main(){\n"
"    gl_Position = u_mvp * vec4(a_pos, 1.0);\n"
"    v_fragDepth = 1.0 + gl_Position.w;\n"
"}\n";

static const char* FS_WORLD =
"#version 330 core\n"
"in float v_fragDepth;\n"
"uniform float u_logCoeff;\n"
"uniform vec3 u_color;\n"
"out vec4 fragColor;\n"
"void main(){\n"
"    gl_FragDepth = log2(v_fragDepth) * u_logCoeff;\n"
"    fragColor = vec4(u_color, 1.0);\n"
"}\n";

// Reflector surface shader.
static const char* VS_REFLECTOR =
"#version 330 core\n"
"layout(location=0) in vec3 a_pos;\n"
"uniform mat4 u_mvp;\n"
"void main(){\n"
"    gl_Position = u_mvp * vec4(a_pos, 1.0);\n"
"}\n";

static const char* FS_REFLECTOR =
"#version 330 core\n"
"uniform vec3 u_color;\n"
"out vec4 fragColor;\n"
"void main(){\n"
"    fragColor = vec4(u_color, 1.0);\n"
"}\n";

int main(void){
    Display* dpy = XOpenDisplay(NULL);
    if(!dpy){ fprintf(stderr, "cannot open display\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attribs);
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap   = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
        InputOutput, vi->visual, CWColormap|CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glViewport(0, 0, W, H);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);

    GLuint prog_world     = link_program(VS_WORLD, FS_WORLD);
    GLuint prog_reflector = link_program(VS_REFLECTOR, FS_REFLECTOR);

    float quad[] = {
        -1.5f,-1.5f, 0.0f,
         1.5f,-1.5f, 0.0f,
         1.5f, 1.5f, 0.0f,
        -1.5f,-1.5f, 0.0f,
         1.5f, 1.5f, 0.0f,
        -1.5f, 1.5f, 0.0f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, NULL);

    float P[16], T[16], MVP[16];
    mat_perspective(P, 60.0f, 1.0f, 0.1f, 1000.0f);
    float far_plus_one = 1001.0f;
    float log_coeff = 1.0f / log2f(far_plus_one);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    // Wall behind the reflector at z = -5, blue.
    mat_translate_z(T, -5.0f); mat_mul(MVP, P, T);
    glUseProgram(prog_world);
    glUniformMatrix4fv(glGetUniformLocation(prog_world, "u_mvp"),       1, GL_FALSE, MVP);
    glUniform1f(glGetUniformLocation(prog_world, "u_logCoeff"), log_coeff);
    glUniform3f(glGetUniformLocation(prog_world, "u_color"),   0.1f, 0.2f, 0.9f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // Reflector surface in front of the wall at z = -3, red.
    mat_translate_z(T, -3.0f); mat_mul(MVP, P, T);
    glUseProgram(prog_reflector);
    glUniformMatrix4fv(glGetUniformLocation(prog_reflector, "u_mvp"), 1, GL_FALSE, MVP);
    glUniform3f(glGetUniformLocation(prog_reflector, "u_color"), 0.9f, 0.1f, 0.1f);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);

    unsigned char px[4];
    glReadPixels(W/2, H/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel rgba=%u,%u,%u,%u\n", px[0], px[1], px[2], px[3]);

    glDeleteProgram(prog_world);
    glDeleteProgram(prog_reflector);
    glDeleteVertexArrays(1, &vao);
    glDeleteBuffers(1, &vbo);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}