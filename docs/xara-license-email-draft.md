# Draft: xara license-confirmation email

Per design doc 0001 §10 Q10 and ADR 0003 — to be sent by the product owner as the
commercial entity. Non-blocking for implementation. Status: **drafted, not yet sent.**

---

**To:** Claudio Perez (STAIRLab, UC Berkeley)
**Subject:** Confirming BSD-2-Clause scope for xara — inherited OpenSees core

Hi Claudio,

I'm a licensed structural engineer building commercial structural engineering
software, and we're evaluating xara as the analysis engine behind a server-side
solver service. The clean OpenSeesPy-compatible API and the performance work have
been impressive — thank you for maintaining it.

Before we build a commercial dependency on it, I'd like to confirm one licensing
point. The xara repository carries a BSD-2-Clause license. Much of the tree is
inherited from upstream OpenSees, which is distributed under the UC license reserving
commercial redistribution rights. Could you confirm that:

1. the BSD-2-Clause license is intended to apply to the whole xara tree — the
   inherited OpenSees core included, not only new STAIRLab contributions; and
2. that relicensing is authorized by the copyright holder (the UC Regents / PEER)?

If there's a written authorization or a public statement of that intent you can point
me to, that would fully settle it on our end.

To be clear about our use: xara would run server-side inside our own service (linear
and, later, nonlinear building-frame analysis); we would not redistribute xara itself
in a desktop product. We're happy to credit xara and report issues upstream as we go.

Thanks for your time — and for the work on xara generally.

Best regards,
Mark Flamer, PE
