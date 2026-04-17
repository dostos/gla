from PIL import Image
Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save("solid_red.png")
Image.new("RGBA", (64, 64), (0, 0, 255, 255)).save("solid_blue.png")

img = Image.new("RGBA", (64, 64), (0, 0, 255, 255))
for x in range(24, 40):
    for y in range(24, 40):
        img.putpixel((x, y), (255, 0, 0, 255))
img.save("red_center_blue_bg.png")
