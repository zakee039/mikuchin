// Standalone CPU thread selection policy used by the native Poly engine.
// Based on PolyStrata 95e8fadb; keep it testable without CUDA or model weights.
#pragma once

namespace strata::poly {

constexpr int auto_cpu_threads(int usable, bool cpu_quota_set) {
    if (usable < 1) return 1;
    return cpu_quota_set ? usable : ((usable * 7 + 5) / 10 > 0 ? (usable * 7 + 5) / 10 : 1);
}

}  // namespace strata::poly
