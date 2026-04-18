// SOURCE: https://github.com/godotengine/godot/issues/112418
// Reproduces Godot 4.6-dev3 SSR NaN propagation: copy.glsl sanitizes higher
// mip levels but not the base level, so a single NaN pixel from a material
// contaminates the screen-space reflection output when half-size is off.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

typedef GLXContext (*CtxAttribsProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define W 64
#define H 64

static const char *VS =
"#version 330 core\n"
"out vec2 uv;\n"
"void main(){ vec2 p=vec2((gl_VertexID<<1)&2, gl_VertexID&2); uv=p; gl_Position=vec4(p*2-1,0,1);}\n";

// Pass 1: mimic a material that writes NaN at one pixel (the "bad object" in the MRP).
static const char *FS_BASE =
"#version 330 core\n"
"in vec2 uv; out vec4 o;\n"
"void main(){\n"
"  if(abs(uv.x-0.5)<0.02 && abs(uv.y-0.5)<0.02){\n"
"    float n = 0.0/0.0; o = vec4(n,n,n,1);\n"
"  } else o = vec4(0.2,0.5,0.8,1);\n"
"}\n";

// Pass 2: mimic copy.glsl higher-mip downsample that sanitizes NaN.
static const char *FS_MIP =
"#version 330 core\n"
"in vec2 uv; out vec4 o;\n"
"uniform sampler2D src; uniform int lod;\n"
"void main(){\n"
"  vec4 c = textureLod(src, uv, float(lod));\n"
"  if(any(isnan(c))) c = vec4(0);\n"
"  o = c;\n"
"}\n";

// Pass 3: sample the unsanitized base level — bilinear filtering spreads the NaN.
static const char *FS_SHOW =
"#version 330 core\n"
"in vec2 uv; out vec4 o;\n"
"uniform sampler2D src;\n"
"void main(){ o = texture(src, uv); }\n";

static GLuint makeProg(const char *vs, const char *fs) {
    GLuint v = glCreateShader(GL_VERTEX_SHADER); glShaderSource(v,1,&vs,NULL); glCompileShader(v);
    GLuint f = glCreateShader(GL_FRAGMENT_SHADER); glShaderSource(f,1,&fs,NULL); glCompileShader(f);
    GLuint p = glCreateProgram(); glAttachShader(p,v); glAttachShader(p,f); glLinkProgram(p);
    GLint ok; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if(!ok){ char log[1024]; glGetProgramInfoLog(p,1024,NULL,log); fprintf(stderr,"link:%s\n",log); }
    return p;
}

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if(!d){ fprintf(stderr,"no display\n"); return 1; }
    int fbattr[] = { GLX_DRAWABLE_TYPE, GLX_PBUFFER_BIT, GLX_RENDER_TYPE, GLX_RGBA_BIT,
                     GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8, None };
    int nfbc = 0;
    GLXFBConfig *fbcs = glXChooseFBConfig(d, DefaultScreen(d), fbattr, &nfbc);
    if(!fbcs || !nfbc){ fprintf(stderr,"no fbconfig\n"); return 1; }
    CtxAttribsProc cca = (CtxAttribsProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctxattr[] = { GLX_CONTEXT_MAJOR_VERSION_ARB, 3, GLX_CONTEXT_MINOR_VERSION_ARB, 3,
                      GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB, None };
    GLXContext ctx = cca(d, fbcs[0], NULL, True, ctxattr);
    int pattr[] = { GLX_PBUFFER_WIDTH, W, GLX_PBUFFER_HEIGHT, H, None };
    GLXPbuffer pb = glXCreatePbuffer(d, fbcs[0], pattr);
    glXMakeCurrent(d, pb, ctx);

    GLuint tex; glGenTextures(1,&tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    int levels = 0, wtmp = W; while(wtmp){ levels++; wtmp>>=1; }
    for (int lv = 0; lv < levels; lv++) {
        int lw = W>>lv, lh = H>>lv; if(lw<1)lw=1; if(lh<1)lh=1;
        glTexImage2D(GL_TEXTURE_2D, lv, GL_RGBA16F, lw, lh, 0, GL_RGBA, GL_FLOAT, NULL);
    }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, 0);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, levels-1);

    GLuint vao; glGenVertexArrays(1,&vao); glBindVertexArray(vao);
    GLuint fbo; glGenFramebuffers(1,&fbo);

    GLuint pbase = makeProg(VS, FS_BASE);
    GLuint pmip  = makeProg(VS, FS_MIP);
    GLuint pshow = makeProg(VS, FS_SHOW);

    // Pass 1: render base mip without NaN guard.
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    glViewport(0,0,W,H);
    glUseProgram(pbase);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    // Pass 2: fill higher mips WITH NaN guard (as copy.glsl does at L86).
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, tex);
    glUseProgram(pmip);
    glUniform1i(glGetUniformLocation(pmip,"src"), 0);
    for (int lv = 1; lv < levels; lv++) {
        int lw = W>>lv, lh = H>>lv; if(lw<1)lw=1; if(lh<1)lh=1;
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, lv);
        glViewport(0,0,lw,lh);
        glUniform1i(glGetUniformLocation(pmip,"lod"), lv-1);
        glDrawArrays(GL_TRIANGLES, 0, 3);
    }

    // Pass 3: sample unsanitized base level — NaN pollutes bilinear neighborhood.
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glViewport(0,0,W,H);
    glUseProgram(pshow);
    glUniform1i(glGetUniformLocation(pshow,"src"), 0);
    glDrawArrays(GL_TRIANGLES, 0, 3);

    unsigned char *pix = (unsigned char*)malloc(W*H*4);
    glReadBuffer(GL_BACK);
    glReadPixels(0,0,W,H,GL_RGBA,GL_UNSIGNED_BYTE,pix);
    int black = 0;
    for (int i = 0; i < W*H; i++)
        if (pix[4*i] < 10 && pix[4*i+1] < 10 && pix[4*i+2] < 10) black++;
    fprintf(stderr, "black_pixels=%d\n", black);
    free(pix);

    glXMakeCurrent(d, None, NULL);
    glXDestroyContext(d, ctx);
    glXDestroyPbuffer(d, pb);
    XCloseDisplay(d);
    return 0;
}