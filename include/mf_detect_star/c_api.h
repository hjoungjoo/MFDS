/* SPDX-License-Identifier: LicenseRef-Cedar-FSL-1.1-MIT-5year */
#ifndef MF_DETECT_STAR_C_API_H
#define MF_DETECT_STAR_C_API_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int mfds_abi_version(void);
/* pixels: uint16 row-major RAW, stride in samples. yxf: capacity*3 floats.
 * Output triples are original sensor y, x, flux. No ownership transfers.
 * Returns count or a negative error; elapsed_ms excludes caller IO.
 * max_value is the sensor saturation scale; use 65535 for synthesized
 * 12-bit preprocessing output whose saturated sensor objects were masked.
 * binning: 1, 2, 4 or 8; sigma must be positive. Capacity is limited to 4096.
 */
int mfds_detect_u16(const uint16_t*, size_t, size_t, size_t, unsigned, int,
                    float, float*, size_t, double*);
/* Experimental optional original-pixel refinement; baseline remains above. */
int mfds_detect_u16_refined(const uint16_t*, size_t, size_t, size_t, unsigned, int,
                            float, float*, size_t, double*);
/* Experimental coarse search (normally binning=4) -> 2x ROI -> optional 1x ROI. */
int mfds_detect_u16_pyramid(const uint16_t*, size_t, size_t, size_t, unsigned, int,
                            float, float*, size_t, double*);
int mfds_detect_u16_pyramid_full(const uint16_t*, size_t, size_t, size_t, unsigned, int,
                                 float, float*, size_t, double*);
#ifdef __cplusplus
}
#endif
#endif
