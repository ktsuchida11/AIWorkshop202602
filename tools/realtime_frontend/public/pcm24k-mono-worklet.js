// AudioWorkletProcessor: input Float32 -> resample 24kHz -> PCM16 mono (ArrayBuffer)

class PCM24kMonoProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 24000;
    this.sourceRate = sampleRate; // AudioContext sample rate
    this.ratio = this.sourceRate / this.targetRate;

    this._pos = 0;          // position in input samples (float)
    this._last = 0.0;       // last sample for interpolation continuity
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || input[0].length === 0) return true;

    // downmix to mono
    const ch0 = input[0];
    const ch1 = input.length > 1 ? input[1] : null;

    const mono = ch1
      ? this._mixToMono(ch0, ch1)
      : ch0;

    // resample to 24k
    const out = this._resampleLinear(mono);

    // float [-1,1] -> PCM16 little-endian
    const pcm16 = new Int16Array(out.length);
    for (let i = 0; i < out.length; i++) {
      let s = Math.max(-1, Math.min(1, out[i]));
      pcm16[i] = (s * 0x7fff) | 0;
    }

    // transfer ArrayBuffer to main thread
    this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    return true;
  }

  _mixToMono(a, b) {
    const n = Math.min(a.length, b.length);
    const m = new Float32Array(n);
    for (let i = 0; i < n; i++) m[i] = 0.5 * (a[i] + b[i]);
    return m;
  }

  _resampleLinear(inBuf) {
    // Generate output samples at target rate using linear interpolation.
    // Maintain a running fractional position in the input buffer.
    const estOut = Math.floor(inBuf.length / this.ratio);
    const out = new Float32Array(Math.max(0, estOut));

    let outIdx = 0;
    let pos = this._pos;

    while (pos < inBuf.length - 1) {
      const i = Math.floor(pos);
      const frac = pos - i;
      const s0 = (i >= 0) ? inBuf[i] : this._last;
      const s1 = inBuf[i + 1];

      out[outIdx++] = s0 + (s1 - s0) * frac;
      pos += this.ratio;
    }

    // store continuity state
    this._pos = pos - inBuf.length;
    this._last = inBuf[inBuf.length - 1];

    return out.subarray(0, outIdx);
  }
}

registerProcessor("pcm24k-mono", PCM24kMonoProcessor);
