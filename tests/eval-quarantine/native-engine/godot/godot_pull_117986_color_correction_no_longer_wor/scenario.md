## User Report

### Tested versions

Reproducible in 4.6.1.stable
Not reproducible in 4.5.1.stable
Not reproducible in 4.5.2.stable

### System information

Godot v4.6.1.stable - Windows 11 (build 26200) - Multi-window, 1 monitor - Vulkan (Mobile) - dedicated NVIDIA GeForce GTX 1660 SUPER (NVIDIA; 32.0.15.9186) - Intel(R) Core(TM) i7-10700F CPU @ 2.90GHz (16 threads) - 15.92 GiB memory

### Issue description

`Environment.adjustment_color_correction` no longer works in 4.6 on Mobile renderer. Still works in Forward+ and Compatibility.

This is a scene with a red-blue LUT in `4.5.1`:
<img width="854" height="715" alt="Image" src="https://github.com/user-attachments/assets/d9fdfe5e-f08a-4111-bfec-c31f2001c355" />

Here is same setup in `4.5.2`:
<img width="844" height="718" alt="Image" src="https://github.com/user-attachments/assets/30d56b62-b06c-4342-9e58-688c76409af3" />

Here it is in `4.6.1`:

<img width="844" height="718" alt="Image" src="https://github.com/user-attachments/assets/67525f44-458e-494d-a679-c696b3196427" />

### Steps to reproduce

Open attached scene and look at the viewport.

### Minimal reproduction project (MRP)

[bug-report.zip](https://github.com/user-attachments/files/26296082/bug-report.zip)

Closes #117986 (https://github.com/godotengine/godot/pull/117986)
Closes #118064 (https://github.com/godotengine/godot/pull/118064)

## Ground Truth

See fix at https://github.com/godotengine/godot/pull/117986.

## Fix

```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/117986
fix_sha: c772c88b0b94a7d0d500df0f07b48e6a906dbff1
bug_class: framework-internal
files:
  - servers/rendering/renderer_rd/forward_mobile/render_forward_mobile.cpp
```
