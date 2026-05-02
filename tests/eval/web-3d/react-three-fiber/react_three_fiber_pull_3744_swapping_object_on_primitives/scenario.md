## User Report

We currently use a setup like this to have more control over resource management, while still integrating into the event system of r3f:

`<primitive
     object={object}
     onClick={someHandler}
/>`

Occasionaly we need to recreate the object instance. However, when reactively replacing the `object` prop, the onClick handler doesn't seem to get attached properly to the new instance, and breaks. This also happens for other events.

Small repro sandbox: https://codesandbox.io/p/sandbox/elated-forest-tncxhh

While stepping through the click functions, I noticed that the corresponding three.js object of the new object has no "_r3f" prop, and was thus filtered out by the raycast logic. So I assume something seems to be going wrong internally in this case.

Closes #3744 (https://github.com/pmndrs/react-three-fiber/pull/3744)

## Ground Truth

See fix at https://github.com/pmndrs/react-three-fiber/pull/3744.

## Fix

```yaml
fix_pr_url: https://github.com/pmndrs/react-three-fiber/pull/3744
fix_sha: 119668f9f3ee31b28485c9706407f22272fe059c
bug_class: framework-internal
files:
  - packages/fiber/src/core/events.ts
  - packages/fiber/src/core/reconciler.tsx
```
