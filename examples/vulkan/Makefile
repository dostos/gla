CC := gcc
CFLAGS := -Wall -Wextra -std=c11 -O2
LIBS := -lvulkan -lm

TARGET := minimal_app
SOURCES := minimal_app.c
OBJECTS := $(SOURCES:.c=.o)

all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(CC) $(CFLAGS) -o $@ $^ $(LIBS)
	@echo "Built: $@"

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

run: $(TARGET)
	export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture; \
	export LD_LIBRARY_PATH=$(HOME)/.config/vulkan/implicit_layer.d:$$LD_LIBRARY_PATH; \
	./$(TARGET)

debug: $(TARGET)
	export VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture; \
	export VK_LAYER_PATH=$(HOME)/.config/vulkan/implicit_layer.d; \
	export VK_LOADER_DEBUG=all; \
	./$(TARGET) 2>&1 | grep -i opengpa || echo "No OpenGPA output (layer may not be installed)"

clean:
	rm -f $(OBJECTS) $(TARGET)

.PHONY: all run debug clean
