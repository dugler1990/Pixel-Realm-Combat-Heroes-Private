# AI-generated asset licensing

This note records a project risk; it is not legal advice.

## Stable Fast 3D

The boss mesh pipeline may use Stability AI's Stable Fast 3D under the
[Stability AI Community License](https://stability.ai/license). That license
permits free commercial use by individuals or organizations whose annual
revenue is below USD 1,000,000 (or the local-currency equivalent), subject to
the complete license terms and acceptable-use policy.

If the applicable individual or organization reaches USD 1,000,000 or more in
annual revenue:

- do not assume meshes or other outputs generated earlier are grandfathered;
- stop generating new assets with Stable Fast 3D;
- before continuing to distribute a commercial product containing its outputs,
  obtain an Enterprise license from Stability AI or replace those outputs with
  assets carrying suitable rights; and
- have qualified counsel review the then-current license and the project's use.

Revenue and licensing status should be reviewed before commercial launch and
whenever annual revenue approaches the threshold. Keep records identifying
which shipped assets were generated with Stable Fast 3D so they can be licensed
or replaced if necessary.

## Rejected alternatives

- Tencent Hunyuan3D-2 and 2.1 were rejected because their community licenses
  exclude use in the European Union, United Kingdom, and South Korea.
- Microsoft TRELLIS's main model and code are MIT-licensed, but CUDA
  dependencies used by its rendering/export path include non-commercial
  restrictions. It was therefore not selected for this commercial project.
