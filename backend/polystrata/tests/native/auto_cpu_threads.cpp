#include "../../src/poly/thread_policy.hpp"

using strata::poly::auto_cpu_threads;
static_assert(auto_cpu_threads(20, false) == 14);
static_assert(auto_cpu_threads(16, false) == 11);
static_assert(auto_cpu_threads(1, false) == 1);
static_assert(auto_cpu_threads(24, true) == 24);
static_assert(auto_cpu_threads(0, true) == 1);

int main() {
    return (auto_cpu_threads(20, false) == 14 &&
            auto_cpu_threads(20, true) == 20) ? 0 : 1;
}
