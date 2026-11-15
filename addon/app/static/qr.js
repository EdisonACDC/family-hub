/* QR codes for the invite links (byte mode, error correction level M, versions 1 to 15).
 *
 * Written for Family Hub after ISO/IEC 18004; the structure follows the well-known approach of
 * Project Nayuki's QR Code generator (MIT licence). No network, no library.
 *
 * window.FH_QR.matrix(text[, mask]) -> array of rows of booleans (true = dark), no quiet zone.
 * window.FH_QR.svg(text) -> an <svg> element, dark on white, with a quiet zone of 4 modules.
 */
(function () {
  "use strict";

  // Level M, by version: error correction codewords per block, and number of blocks.
  var ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24];
  var BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10];
  var MAX_VERSION = 15;
  var FORMAT_M = 0;

  function rawModules(ver) {
    var result = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      var align = Math.floor(ver / 7) + 2;
      result -= (25 * align - 10) * align - 55;
      if (ver >= 7) result -= 36;
    }
    return result;
  }

  function dataCodewords(ver) {
    return Math.floor(rawModules(ver) / 8) - ECC_PER_BLOCK[ver] * BLOCKS[ver];
  }

  function utf8(text) {
    var bytes = [];
    var encoded = unescape(encodeURIComponent(text));
    for (var i = 0; i < encoded.length; i++) bytes.push(encoded.charCodeAt(i));
    return bytes;
  }

  // ---- Reed-Solomon over GF(256), polynomial 0x11D ----
  function multiply(x, y) {
    var z = 0;
    for (var i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11D);
      z ^= ((y >>> i) & 1) * x;
    }
    return z;
  }

  function divisor(degree) {
    var result = [];
    for (var i = 0; i < degree - 1; i++) result.push(0);
    result.push(1);
    var root = 1;
    for (var k = 0; k < degree; k++) {
      for (var j = 0; j < result.length; j++) {
        result[j] = multiply(result[j], root);
        if (j + 1 < result.length) result[j] ^= result[j + 1];
      }
      root = multiply(root, 0x02);
    }
    return result;
  }

  function remainder(data, div) {
    var result = div.map(function () { return 0; });
    data.forEach(function (b) {
      var factor = b ^ result.shift();
      result.push(0);
      div.forEach(function (coef, i) { result[i] ^= multiply(coef, factor); });
    });
    return result;
  }

  // ---- the code words ----
  function encode(bytes, ver) {
    var bits = [];
    function put(value, length) {
      for (var i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1);
    }
    put(4, 4); // byte mode
    put(bytes.length, ver <= 9 ? 8 : 16);
    bytes.forEach(function (b) { put(b, 8); });
    var capacity = dataCodewords(ver) * 8;
    put(0, Math.min(4, capacity - bits.length));
    put(0, (8 - bits.length % 8) % 8);
    for (var pad = 0xEC; bits.length < capacity; pad ^= 0xEC ^ 0x11) put(pad, 8);
    var words = [];
    for (var i = 0; i < bits.length; i += 8) {
      var w = 0;
      for (var j = 0; j < 8; j++) w = (w << 1) | bits[i + j];
      words.push(w);
    }
    return words;
  }

  function withEcc(data, ver) {
    var numBlocks = BLOCKS[ver];
    var eccLen = ECC_PER_BLOCK[ver];
    var raw = Math.floor(rawModules(ver) / 8);
    var shortBlocks = numBlocks - raw % numBlocks;
    var shortLen = Math.floor(raw / numBlocks);
    var div = divisor(eccLen);
    var blocks = [];
    for (var i = 0, k = 0; i < numBlocks; i++) {
      var dat = data.slice(k, k + shortLen - eccLen + (i < shortBlocks ? 0 : 1));
      k += dat.length;
      var ecc = remainder(dat, div);
      if (i < shortBlocks) dat.push(0);
      blocks.push(dat.concat(ecc));
    }
    var result = [];
    for (var n = 0; n < blocks[0].length; n++) {
      for (var b = 0; b < blocks.length; b++) {
        if (n !== shortLen - eccLen || b >= shortBlocks) result.push(blocks[b][n]);
      }
    }
    return result;
  }

  // ---- the picture ----
  function Grid(ver) {
    this.size = ver * 4 + 17;
    this.dark = [];
    this.fixed = [];
    for (var y = 0; y < this.size; y++) {
      this.dark.push(new Array(this.size).fill(false));
      this.fixed.push(new Array(this.size).fill(false));
    }
  }
  Grid.prototype.set = function (x, y, dark) {
    this.dark[y][x] = dark;
    this.fixed[y][x] = true;
  };

  function alignments(ver, size) {
    if (ver === 1) return [];
    var count = Math.floor(ver / 7) + 2;
    var step = Math.ceil((ver * 4 + 4) / (count * 2 - 2)) * 2;
    var result = [6];
    for (var pos = size - 7; result.length < count; pos -= step) result.splice(1, 0, pos);
    return result;
  }

  function drawFixed(grid, ver) {
    var size = grid.size;
    for (var i = 0; i < size; i++) {
      grid.set(6, i, i % 2 === 0);
      grid.set(i, 6, i % 2 === 0);
    }
    [[3, 3], [size - 4, 3], [3, size - 4]].forEach(function (c) {
      for (var dy = -4; dy <= 4; dy++) {
        for (var dx = -4; dx <= 4; dx++) {
          var dist = Math.max(Math.abs(dx), Math.abs(dy));
          var x = c[0] + dx;
          var y = c[1] + dy;
          if (x >= 0 && x < size && y >= 0 && y < size) grid.set(x, y, dist !== 2 && dist !== 4);
        }
      }
    });
    var pos = alignments(ver, size);
    var last = pos.length - 1;
    for (var a = 0; a < pos.length; a++) {
      for (var b = 0; b < pos.length; b++) {
        if ((a === 0 && b === 0) || (a === 0 && b === last) || (a === last && b === 0)) continue;
        for (var ddy = -2; ddy <= 2; ddy++) {
          for (var ddx = -2; ddx <= 2; ddx++) {
            grid.set(pos[a] + ddx, pos[b] + ddy, Math.max(Math.abs(ddx), Math.abs(ddy)) !== 1);
          }
        }
      }
    }
    drawFormat(grid, 0);
    if (ver >= 7) {
      var rem = ver;
      for (var r = 0; r < 12; r++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
      var bits = ver << 12 | rem;
      for (var v = 0; v < 18; v++) {
        var on = ((bits >>> v) & 1) !== 0;
        var p = size - 11 + v % 3;
        var q = Math.floor(v / 3);
        grid.set(p, q, on);
        grid.set(q, p, on);
      }
    }
  }

  function drawFormat(grid, mask) {
    var size = grid.size;
    var data = FORMAT_M << 3 | mask;
    var rem = data;
    for (var i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    var bits = (data << 10 | rem) ^ 0x5412;
    function bit(n) { return ((bits >>> n) & 1) !== 0; }
    for (var a = 0; a <= 5; a++) grid.set(8, a, bit(a));
    grid.set(8, 7, bit(6));
    grid.set(8, 8, bit(7));
    grid.set(7, 8, bit(8));
    for (var b = 9; b < 15; b++) grid.set(14 - b, 8, bit(b));
    for (var c = 0; c < 8; c++) grid.set(size - 1 - c, 8, bit(c));
    for (var d = 8; d < 15; d++) grid.set(8, size - 15 + d, bit(d));
    grid.set(8, size - 8, true);
  }

  function drawData(grid, words) {
    var size = grid.size;
    var i = 0;
    for (var right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (var vert = 0; vert < size; vert++) {
        for (var j = 0; j < 2; j++) {
          var x = right - j;
          var upward = ((right + 1) & 2) === 0;
          var y = upward ? size - 1 - vert : vert;
          if (!grid.fixed[y][x] && i < words.length * 8) {
            grid.dark[y][x] = ((words[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0;
            i++;
          }
        }
      }
    }
  }

  function maskBit(mask, x, y) {
    switch (mask) {
      case 0: return (x + y) % 2 === 0;
      case 1: return y % 2 === 0;
      case 2: return x % 3 === 0;
      case 3: return (x + y) % 3 === 0;
      case 4: return (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0;
      case 5: return x * y % 2 + x * y % 3 === 0;
      case 6: return (x * y % 2 + x * y % 3) % 2 === 0;
      default: return ((x + y) % 2 + x * y % 3) % 2 === 0;
    }
  }

  function applyMask(grid, mask) {
    for (var y = 0; y < grid.size; y++) {
      for (var x = 0; x < grid.size; x++) {
        if (!grid.fixed[y][x] && maskBit(mask, x, y)) grid.dark[y][x] = !grid.dark[y][x];
      }
    }
  }

  // The penalty of a finished picture (lower is better), as the standard counts it.
  function penalty(dark) {
    var size = dark.length;
    var score = 0;
    var finderA = [true, false, true, true, true, false, true, false, false, false, false];
    var finderB = finderA.slice().reverse();
    function line(get) {
      var run = 1;
      for (var i = 1; i <= size; i++) {
        if (i < size && get(i) === get(i - 1)) {
          run++;
        } else {
          if (run >= 5) score += 3 + (run - 5);
          run = 1;
        }
      }
      for (var s = 0; s + 11 <= size; s++) {
        var a = true;
        var b = true;
        for (var k = 0; k < 11; k++) {
          if (get(s + k) !== finderA[k]) a = false;
          if (get(s + k) !== finderB[k]) b = false;
        }
        if (a) score += 40;
        if (b) score += 40;
      }
    }
    for (var y = 0; y < size; y++) line(function (x) { return dark[y][x]; });
    for (var x = 0; x < size; x++) line(function (yy) { return dark[yy][x]; });
    var count = 0;
    for (var r = 0; r < size; r++) {
      for (var c = 0; c < size; c++) {
        if (dark[r][c]) count++;
        if (r + 1 < size && c + 1 < size) {
          var v = dark[r][c];
          if (v === dark[r][c + 1] && v === dark[r + 1][c] && v === dark[r + 1][c + 1]) score += 3;
        }
      }
    }
    var total = size * size;
    score += (Math.ceil(Math.abs(count * 20 - total * 10) / total) - 1) * 10;
    return score;
  }

  function matrix(text, wantedMask) {
    var bytes = utf8(text);
    var ver = 1;
    while (ver <= MAX_VERSION && 4 + (ver <= 9 ? 8 : 16) + bytes.length * 8 > dataCodewords(ver) * 8) ver++;
    if (ver > MAX_VERSION) throw new Error("text too long for a QR code here");
    var words = withEcc(encode(bytes, ver), ver);
    var best = null;
    var bestScore = Infinity;
    var masks = typeof wantedMask === "number" ? [wantedMask] : [0, 1, 2, 3, 4, 5, 6, 7];
    masks.forEach(function (mask) {
      var grid = new Grid(ver);
      drawFixed(grid, ver);
      drawData(grid, words);
      applyMask(grid, mask);
      drawFormat(grid, mask);
      var score = masks.length === 1 ? 0 : penalty(grid.dark);
      if (score < bestScore) {
        bestScore = score;
        best = grid.dark;
      }
    });
    return best;
  }

  function svg(text) {
    var dark = matrix(text);
    var size = dark.length;
    var quiet = 4;
    var full = size + quiet * 2;
    var ns = "http://www.w3.org/2000/svg";
    var root = document.createElementNS(ns, "svg");
    root.setAttribute("viewBox", "0 0 " + full + " " + full);
    root.setAttribute("shape-rendering", "crispEdges");
    root.setAttribute("role", "img");
    var back = document.createElementNS(ns, "rect");
    back.setAttribute("width", String(full));
    back.setAttribute("height", String(full));
    back.setAttribute("fill", "#FFFFFF");
    root.appendChild(back);
    var d = [];
    for (var y = 0; y < size; y++) {
      for (var x = 0; x < size; x++) {
        if (dark[y][x]) d.push("M" + (x + quiet) + " " + (y + quiet) + "h1v1h-1z");
      }
    }
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", d.join(""));
    path.setAttribute("fill", "#000000");
    root.appendChild(path);
    return root;
  }

  window.FH_QR = { matrix: matrix, svg: svg };
})();
