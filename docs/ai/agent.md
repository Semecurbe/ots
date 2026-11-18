# onthesignal — functions available to the assistant

Generated from the command registry and the docstrings (onthesignal 0.1.0). Do not edit by hand: run `/gen_ai_doc`.

## `delay50(S1, S2, ...)` — Delay between two signals at 50 % of their transitions
When to use: “delay / time offset between two signals at 50 % of their edges”; “synchronization between two digitizers”.

Delay ``t(S2) − t(S1)`` between the 50 % crossings of two signals.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `edge` | str | rising |  | Edges measured |
| `level` | float | 0.5 |  | Threshold between the low and high levels (0.5 = 50 %) |
| `levels` | str | histogram |  | Low/high levels: histogram modes (oscilloscope method) or min/max (advanced) |
| `hysteresis` | float | 0.05 |  | Hysteresis, as a fraction of the high − low amplitude (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `delay50(S1, S2, edge=rising, level=0.5)`

## `frequency(S, ...)` — Frequency of a periodic signal (crossings, sine fit or FFT)
When to use: “measure the frequency of a periodic signal”.

Frequency: number of full periods between the first and last rising crossings of the
mean level divided by their time interval (or 4-parameter fit, or FFT peak).

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `method` | str | zero_crossing |  | Crossings of the mean level, 4-parameter sine fit or interpolated FFT peak |
| `hysteresis` | float | 0.05 |  | Hysteresis, as a fraction of the peak-to-peak amplitude (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `frequency(S, method=zero_crossing)`

## `period(S, ...)` — Period of a periodic signal: mean, standard deviation, min, max
When to use: “measure the period and its jitter”.

Period statistics between successive rising crossings of the mean level.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `method` | str | zero_crossing |  | Crossings of the mean level, 4-parameter sine fit or interpolated FFT peak |
| `hysteresis` | float | 0.05 |  | Hysteresis, as a fraction of the peak-to-peak amplitude (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `period(S, method=zero_crossing)`

## `lnm(S, ...)` — PSD compared with the Peterson low-noise model (NLNM)
When to use: “compare the noise with the LNM / NLNM / Peterson low-noise model”; “is the noise of the sensor or digitizer below the low-noise model?”.

Welch PSD of the signal in physical units compared with the Peterson NLNM.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `window` | str | hann |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `nperseg` | int | none |  | Welch segment length in samples (default: largest power of 2 <= N/8) (advanced) |
| `seg_duration` | float | none | s | Welch segment duration (alternative to nperseg) (advanced) |
| `overlap` | float | 0.5 |  | Segment overlap ratio (advanced) |
| `average` | str | mean |  | Averaging of the Welch periodograms (advanced) |
| `smoothing` | int | 8 |  | PSD smoothing in 1/n octave bands (none = no smoothing) |
| `show_nhnm` | bool | false |  | Also show the high-noise model (NHNM) |
| `x` | str | freq |  | Abscissa: frequency or period |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `lnm(S, smoothing=8, show_nhnm=false, x=freq)`

## `noise(S, ...)` — Noise RMS, peak-to-peak, mean and dynamic range in the study band
When to use: “measure the noise of a record without signal (inputs shorted)”; “noise RMS, peak-to-peak, mean, dynamic range in a band”.

Noise of a record without useful signal: RMS, peak-to-peak, mean, dynamic range.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `units` | str | physical |  | Display units (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `noise(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24)`

## `noise_dsp(S, ...)` — Welch power spectral density of the noise with the noise results
When to use: “noise power spectral density (Welch PSD)”; “noise level per √Hz”.

Noise results plus the Welch PSD and the RMS obtained by integrating it over the band.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `units` | str | physical |  | Display units (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |
| `window` | str | hann |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `nperseg` | int | none |  | Welch segment length in samples (default: largest power of 2 <= N/8) (advanced) |
| `seg_duration` | float | none | s | Welch segment duration (alternative to nperseg) (advanced) |
| `overlap` | float | 0.5 |  | Segment overlap ratio (advanced) |
| `average` | str | mean |  | Averaging of the Welch periodograms (advanced) |
| `scale` | str | psd |  | psd: dB re 1 unit²/Hz; asd: amplitude density (unit/√Hz) |
| `cumulative` | bool | false |  | Also plot the cumulative RMS versus frequency |
| `xscale` | str | log |  | Frequency axis scale (advanced) |

Example: `noise_dsp(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24, scale=psd, cumulative=false)`

## `noise_fft(S, ...)` — Amplitude spectrum (FFT) of the noise with the noise results
When to use: “show the noise spectrum (FFT) with the noise results”.

Noise results plus the one-sided amplitude spectrum of the detrended record.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `units` | str | physical |  | Display units (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |
| `window` | str | hann |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `scale` | str | amplitude |  | Spectrum scale: peak amplitude, RMS, amplitude density or dBFS |
| `xscale` | str | log |  | Frequency axis scale (advanced) |

Example: `noise_fft(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24, scale=amplitude)`

## `dynamic(S, ...)` — SINAD, ENOB, SFDR, THD and SNR from a single sine fit
When to use: “complete dynamic test of a sine: SINAD, ENOB, SFDR, THD, SNR at once”; “dynamic report”.

Dynamic analysis: SINAD, ENOB, SFDR, THD and SNR computed from one sine fit.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `f0` | float | none | Hz | Approximate sine frequency (none = automatic) |
| `tol` | float | 1e-09 |  | Convergence threshold on |Δω/ω| (advanced) |
| `maxiter` | int | 100 |  | Maximum number of iterations (advanced) |
| `units` | str | physical |  | Display units (advanced) |
| `xscale` | str | log |  | Frequency axis scale (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |
| `n_harmonics` | int | 10 |  | Highest harmonic order (H2 to Hn) |
| `window` | str | blackmanharris |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `exclude_f0` | float | none | Hz | Half-width excluded around the fundamental (default: 3 main-lobe half-widths) (advanced) |
| `emergence` | float | 6.0 | dB | Margin above the expected noise maximum for a spur to count as a real line (advanced) |
| `noise` | object | none |  | Noise record (no signal) used for the dynamic range |
| `report` | bool | false |  | Generate a Quarto report |

Example: `dynamic(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24, f0=none, n_harmonics=10, report=false)`

## `sfdr(S, ...)` — Spurious-free dynamic range from the spectrum of the fit residual
When to use: “SFDR”; “largest spurious line”.

SFDR: ratio between the fundamental and the largest spur in the study band.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `f0` | float | none | Hz | Approximate sine frequency (none = automatic) |
| `tol` | float | 1e-09 |  | Convergence threshold on |Δω/ω| (advanced) |
| `maxiter` | int | 100 |  | Maximum number of iterations (advanced) |
| `units` | str | physical |  | Display units (advanced) |
| `xscale` | str | log |  | Frequency axis scale (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |
| `window` | str | blackmanharris |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `exclude_f0` | float | none | Hz | Half-width excluded around the fundamental (default: 3 main-lobe half-widths) (advanced) |
| `emergence` | float | 6.0 | dB | Margin above the expected noise maximum for a spur to count as a real line (advanced) |

Example: `sfdr(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24, f0=none)`

## `sinad(S, ...)` — SINAD and ENOB from the residual of a 4-parameter sine fit
When to use: “SINAD”; “ENOB / effective number of bits”; “noise on a sine (4-parameter fit)”.

SINAD and ENOB.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `f0` | float | none | Hz | Approximate sine frequency (none = automatic) |
| `tol` | float | 1e-09 |  | Convergence threshold on |Δω/ω| (advanced) |
| `maxiter` | int | 100 |  | Maximum number of iterations (advanced) |
| `units` | str | physical |  | Display units (advanced) |
| `xscale` | str | log |  | Frequency axis scale (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `sinad(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24, f0=none)`

## `sinefit(S, ...)` — 4-parameter sine fit (IEEE 1057): amplitude, phase, offset, frequency
When to use: “fit a sine: amplitude, frequency, phase and offset of a test sine”.

4-parameter sine fit of the record: amplitude, phase, offset, frequency and residual.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `f0` | float | none | Hz | Approximate sine frequency (none = automatic) |
| `tol` | float | 1e-09 |  | Convergence threshold on |Δω/ω| (advanced) |
| `maxiter` | int | 100 |  | Maximum number of iterations (advanced) |
| `units` | str | physical |  | Display units (advanced) |
| `t_start` | object | none |  | Start of the analysed window (advanced) |
| `t_end` | object | none |  | End of the analysed window (advanced) |

Example: `sinefit(S, f0=none)`

## `thd(S, ...)` — Total harmonic distortion (multi-harmonic least-squares fit)
When to use: “THD”; “harmonic distortion of a test sine”.

THD = sqrt(sum of A_k², k = 2..n) / A_1, harmonics fitted by linear least squares.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `fmin` | float | 0.0 | Hz | Lower bound of the study band (0 = no high-pass) |
| `fmax` | float | 100.0 | Hz | Upper bound of the study band (low-pass) |
| `remove_mains` | bool | false |  | Remove the mains line and its harmonics |
| `mains_freq` | float | 50.0 | Hz | Mains frequency (advanced) |
| `mains_width` | float | 1.0 | Hz | Total width removed around each mains line (advanced) |
| `mains_harmonics` | int | none |  | Number of mains lines removed (none = all up to fmax) (advanced) |
| `filter_method` | str | fft |  | Band limitation: ideal FFT mask or zero-phase Butterworth (advanced) |
| `filter_order` | int | 4 |  | Butterworth order (iir method) (advanced) |
| `detrend` | str | constant |  | Trend removal before analysis (advanced) |
| `full_scale` | float | 2**24 | counts | Digitizer full scale, peak-to-peak |
| `f0` | float | none | Hz | Approximate sine frequency (none = automatic) |
| `tol` | float | 1e-09 |  | Convergence threshold on |Δω/ω| (advanced) |
| `maxiter` | int | 100 |  | Maximum number of iterations (advanced) |
| `units` | str | physical |  | Display units (advanced) |
| `xscale` | str | log |  | Frequency axis scale (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |
| `n_harmonics` | int | 10 |  | Highest harmonic order (H2 to Hn) |

Example: `thd(S, fmin=0.0, fmax=100.0, remove_mains=false, full_scale=2**24, f0=none, n_harmonics=10)`

## `coherence(S1, S2, ...)` — Magnitude-squared coherence between two signals (Welch)
When to use: “coherence between two channels or two instruments”.

Magnitude-squared coherence ``|Pxy|² / (Pxx Pyy)`` estimated with Welch's method.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `window` | str | hann |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `nperseg` | int | none |  | Welch segment length in samples (default: largest power of 2 <= N/8) (advanced) |
| `seg_duration` | float | none | s | Welch segment duration (alternative to nperseg) (advanced) |
| `overlap` | float | 0.5 |  | Segment overlap ratio (advanced) |
| `average` | str | mean |  | Averaging of the Welch periodograms (advanced) |
| `fmin` | float | 0.0 | Hz | Lower bound for the mean coherence |
| `fmax` | float | none | Hz | Upper bound for the mean coherence (none = Nyquist) |
| `significance` | bool | false |  | Draw the zero-coherence significance level |
| `alpha` | float | 0.05 |  | Risk level of the significance threshold (advanced) |
| `xscale` | str | log |  | Frequency axis scale (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `coherence(S1, S2, fmin=0.0, fmax=none, significance=false)`

## `spectrogram(S, ...)` — Spectrogram (short-time PSD) of a signal
When to use: “time-frequency view of a signal (spectrogram)”.

Short-time Fourier PSD in dB re 1 unit²/Hz.

| Parameter | Type | Default | Unit | Description |
|---|---|---|---|---|
| `window` | str | hann |  | Spectral window (hann, blackmanharris, flattop, boxcar...) (advanced) |
| `win_duration` | float | none | s | Window duration (default: about 100 time slices) |
| `overlap` | float | 0.5 |  | Window overlap (advanced) |
| `fmin` | float | 0.0 | Hz | Lowest frequency shown |
| `fmax` | float | none | Hz | Highest frequency shown (none = Nyquist) |
| `yscale` | str | linear |  | Frequency axis scale |
| `vmin` | float | none | dB | Lower color limit (default: 1st percentile) (advanced) |
| `vmax` | float | none | dB | Upper color limit (default: 99th percentile) (advanced) |
| `show_signal` | bool | true |  | Show the time series above the spectrogram |
| `units` | str | physical |  | Display units (advanced) |
| `t_start` | object | none |  | Start of the analysed window (UTC time or seconds from start) (advanced) |
| `t_end` | object | none |  | End of the analysed window (UTC time or seconds from start) (advanced) |

Example: `spectrogram(S, win_duration=none, fmin=0.0, fmax=none, yscale=linear, show_signal=true)`
