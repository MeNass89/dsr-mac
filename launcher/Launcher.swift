// Dark Souls Remastered launcher: the app's main executable. A settings window (graphics, controls, audio, mods, saves) in front of the game; Play starts dmhost with the
// matching environment and the window comes back when the game ends. Hold Option at launch to see the window when "skip this window" is on.
// Build: swiftc -O -parse-as-library Launcher.swift -o DarkSouls (install.sh step 8)
import SwiftUI
import UniformTypeIdentifiers
import AppKit
import GameController

// MARK: - Text (French when the system prefers it, English otherwise)
let fr = (Locale.preferredLanguages.first ?? "en").hasPrefix("fr")
func T(_ en: String, _ f: String) -> String { fr ? f : en }

// MARK: - Paths
let bundleMacOS = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS")
let bundleRes = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources")
let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/nxnative/DarkSoulsRemastered")
// The game data (romfs, msl, main*, games, pctextures, glyphs) lives outside the signed app: macOS scans a freshly signed bundle in full before its first
// launch (16-34 min for 4 GB). install.sh writes its folder into Resources/game-path (default <support>/game). Apps built before v1.0.2 keep it in Resources/game.
let gameRes: URL = {
    let fm = FileManager.default
    var c: [URL] = []
    if let p = try? String(contentsOf: bundleRes.appendingPathComponent("game-path"), encoding: .utf8) {
        let t = p.trimmingCharacters(in: .whitespacesAndNewlines); if !t.isEmpty { c.append(URL(fileURLWithPath: t)) }
    }
    c += [support.appendingPathComponent("game"), bundleRes.appendingPathComponent("game")]
    return c.first { fm.fileExists(atPath: $0.appendingPathComponent("romfs").path) } ?? c[0]
}()
let modsDir = support.appendingPathComponent("mods")
let overlayDir = support.appendingPathComponent("overlay")
let backupsDir = support.appendingPathComponent("backups")
let saveDir = support.appendingPathComponent("save")
let logFile = support.appendingPathComponent("last-run.log")

// MARK: - Settings
struct Settings: Codable, Equatable {
    var resolution = 1080          // 1080, 1440, 2160
    var fps = 60                   // 60, 90, 120
    var fullscreen = false
    var perfOverlay = false
    var faceButtons = "position"   // position (Xbox / PlayStation layout) or label (Nintendo letters)
    var buttonPrompts = "auto"     // on-screen button pictures: auto (by the connected controller), switch, playstation, xbox
    var volume = 100.0
    var skipWindow = false
    var mods: [String: Bool] = [:] // mod folder name → enabled
    var modOrder: [String] = []    // priority, first wins
    var textures = "switch"        // switch, or pc: the PC version's textures where they are better (game/pctextures, built from the user's PC copy)
    var pack = true                // the recommended mod pack (Resources/pack: the mods whose authors allow re-upload), converted at first use
    var record = false             // settings.json only: log every controller and key input (DM_PADLOG, DM_KEYLOG) into the run's log, for a test session
    var colorspace = ""            // "", srgb or p3: the game layer's colour space tag (DM_LAYER_COLORSPACE; settings.json only, a test for the fullscreen purple bands on XDR)
}
extension Settings {   // missing keys keep their defaults, so a settings file from an older launcher still loads
    enum K: String, CodingKey { case resolution, fps, fullscreen, perfOverlay, faceButtons, buttonPrompts, volume, skipWindow, mods, modOrder, textures, colorspace, pack, record }
    init(from dec: Decoder) throws {
        self.init(); let c = try dec.container(keyedBy: K.self)
        func g<T: Decodable>(_ k: K, _ v: inout T) { if let x = try? c.decode(T.self, forKey: k) { v = x } }
        g(.resolution, &resolution); g(.fps, &fps); g(.fullscreen, &fullscreen); g(.perfOverlay, &perfOverlay); g(.faceButtons, &faceButtons)
        g(.buttonPrompts, &buttonPrompts); g(.volume, &volume); g(.skipWindow, &skipWindow); g(.mods, &mods); g(.modOrder, &modOrder); g(.textures, &textures); g(.colorspace, &colorspace); g(.pack, &pack); g(.record, &record)
    }
}
func loadSettings() -> Settings {
    guard let d = try? Data(contentsOf: support.appendingPathComponent("settings.json")), let s = try? JSONDecoder().decode(Settings.self, from: d) else { return Settings() }
    return s
}
func saveSettings(_ s: Settings) {
    let e = JSONEncoder(); e.outputFormatting = [.prettyPrinted, .sortedKeys]
    try? e.encode(s).write(to: support.appendingPathComponent("settings.json"))
}

// MARK: - Mods: FromSoftware archives (BHD5 index + BDT data). A mod is a folder of game files by their archive path (the layout UXM unpacks on PC: chr/, parts/, map/,
// msg/ENGLISH/, param/gameparam/, sfx/, menu/ ...). Installing rewrites the small index into the overlay and appends the files after the archive's end (dmhost reads
// "<archive>.append" past the end of the archive), so the game sees them in place of the originals. New files that the game does not list cannot be added.
struct ModReport { var replaced = 0; var unknown: [String] = [] }
func fsHash(_ path: String) -> UInt32 {
    var h: UInt32 = 0
    for c in path.lowercased().replacingOccurrences(of: "\\", with: "/").utf8 { h = h &* 37 &+ UInt32(c) }
    return h
}
func modRoot(_ dir: URL) -> URL {   // a mod zipped with an extra top folder ("MyMod/MyMod/chr/..." or ".../data/chr/...")
    let fm = FileManager.default
    let kids = ((try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.isDirectoryKey])) ?? []).filter { !$0.lastPathComponent.hasPrefix(".") }
    let known: Set<String> = ["chr", "parts", "map", "msg", "param", "sfx", "menu", "font", "obj", "other", "event", "facegen", "mtd", "paramdef", "remo", "script", "shader", "sound", "movww"]
    if kids.contains(where: { known.contains($0.lastPathComponent.lowercased()) }) { return dir }
    if kids.count == 1, (try? kids[0].resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true { return modRoot(kids[0]) }
    return dir
}
func modFiles(_ dir: URL) -> [(String, URL)] {
    let root = dir.resolvingSymlinksInPath()   // the enumerator reports resolved paths (/tmp is /private/tmp): cut the same prefix
    var out: [(String, URL)] = []
    guard let en = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey]) else { return out }
    for case let u as URL in en where (try? u.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true {
        let rel = u.resolvingSymlinksInPath().path.dropFirst(root.path.count)
        if u.lastPathComponent.hasPrefix(".") || u.pathExtension.lowercased() == "txt" || u.pathExtension.lowercased() == "md" { continue }
        out.append((String(rel), u))
    }
    return out
}
// PC mods: Nexus mods are made for the PC game, whose files do not load on the Switch build (other archive flags and names, NVN textures, PC-only content).
// tools/dsr-mods/port_mod.py (copied next to the game data by install.sh) merges each mod file into the matching Switch file; the result is cached in
// mods-ported/<mod>, keyed by the mod's file list, sizes and dates, and is what the overlay installs. port.tsv there says what happened to each file.
let portedDir = support.appendingPathComponent("mods-ported")
func portTool() -> URL? {
    for u in [gameRes.appendingPathComponent("tools/dsr-mods/port_mod.py"), bundleRes.appendingPathComponent("dsr-mods/port_mod.py")] where FileManager.default.fileExists(atPath: u.path) { return u }
    return nil
}
// base: the files of the mods applied before this one (a cumulative stack, see buildOverlay); the converter merges this mod onto them, so two mods that
// change the same archive (menu text, menu textures) both land. The output then holds the base's files too and replaces it.
func portedMod(_ dir: URL, base: URL? = nil, name: String? = nil) -> URL {   // name: the mod's name in the list (its inner folder may be "Texture Override" in several mods)
    guard let tool = portTool() else { return dir }
    let fm = FileManager.default, out = portedDir.appendingPathComponent(name ?? dir.lastPathComponent), stamp = out.appendingPathComponent(".source")
    let key = modFiles(dir).map { (rel, u) -> String in
        let a = try? fm.attributesOfItem(atPath: u.path)
        return "\(rel)\t\((a?[.size] as? UInt64) ?? 0)\t\(((a?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0))"
    }.sorted().joined(separator: "\n") + "\n" + ((try? String(contentsOf: tool, encoding: .utf8))?.count.description ?? "")
        + "\nbase " + (base.flatMap { try? String(contentsOf: $0.appendingPathComponent(".source"), encoding: .utf8) }.map { k in String(k.utf8.reduce(UInt64(1469598103934665603)) { ($0 ^ UInt64($1)) &* 1099511628211 }) } ?? "-")   // FNV-1a of the base's key
    if (try? String(contentsOf: stamp, encoding: .utf8)) == key { return out }
    try? fm.removeItem(at: out); try? fm.createDirectory(at: out, withIntermediateDirectories: true)
    // The Python install.sh ran (game/tools/python: it has numpy etcpak texture2ddecoder in its user site-packages, so no -I), else python3 on PATH
    let py = (try? String(contentsOf: gameRes.appendingPathComponent("tools/python"), encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let p = Process(); p.executableURL = URL(fileURLWithPath: py.isEmpty ? "/usr/bin/env" : py)
    var args: [String] = py.isEmpty ? ["python3"] : []
    args += ["-B", tool.path]; if let b = base { args += ["--base", b.path] }
    args += [dir.path, gameRes.appendingPathComponent("romfs").path, out.path]; p.arguments = args
    p.currentDirectoryURL = out
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    do { try p.run(); p.waitUntilExit() } catch { return dir }
    guard p.terminationStatus == 0 else { return dir }   // Python or its modules missing: the mod goes in as it is, as before
    if let b = base {   // carry the base's files the mod did not touch, so the output is the whole stack so far
        for (rel, u) in modFiles(b) where !rel.hasSuffix(".tsv") && !rel.hasSuffix("/.source") {
            let dst = out.appendingPathComponent(rel); if fm.fileExists(atPath: dst.path) { continue }
            try? fm.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true); try? fm.copyItem(at: u, to: dst)   // APFS clone
        }
    }
    try? key.write(to: stamp, atomically: true, encoding: .utf8)
    return out
}
// The recommended pack: Resources/pack/pack.tsv lists the mods (id, name, author, included|download, Nexus page, file, folder, what it does) and
// Resources/pack/included/ holds the PC files of the included ones as their authors released them. tools/dsr-mods/build_pack.py converts them onto
// this Mac's own Switch files and stacks them (mods-ported/_pack/_stack), once per pack and converter version. Nothing from the game ships.
struct PackMod: Identifiable { let id, name, author, status, nexus, file, folder, what: String }
let packDir = bundleRes.appendingPathComponent("pack")
func packMods() -> [PackMod] {
    guard let t = try? String(contentsOf: packDir.appendingPathComponent("pack.tsv"), encoding: .utf8) else { return [] }
    return t.split(separator: "\n").compactMap { l in
        if l.hasPrefix("#") { return nil }
        let f = l.split(separator: "\t", omittingEmptySubsequences: false).map(String.init); guard f.count >= 8 else { return nil }
        return PackMod(id: f[0], name: f[1], author: f[2], status: f[3], nexus: f[4], file: f[5], folder: f[6], what: f[7])
    }
}
func packStack() -> URL? {
    let fm = FileManager.default, out = portedDir.appendingPathComponent("_pack"), stack = out.appendingPathComponent("_stack"), stamp = out.appendingPathComponent(".source")
    guard let tool = portTool()?.deletingLastPathComponent().appendingPathComponent("build_pack.py"), fm.fileExists(atPath: tool.path),
          let list = try? String(contentsOf: packDir.appendingPathComponent("pack.tsv"), encoding: .utf8) else { return nil }
    let conv = ["port_mod.py", "build_pack.py", "esd.py", "tae.py", "msb.py", "fsb.py", "fmg.py"].map { (try? String(contentsOf: tool.deletingLastPathComponent().appendingPathComponent($0), encoding: .utf8))?.count ?? 0 }
    let key = list + "\n" + conv.map(String.init).joined(separator: ",")
    if (try? String(contentsOf: stamp, encoding: .utf8)) == key, fm.fileExists(atPath: stack.path) { return stack }
    try? fm.removeItem(at: out); try? fm.createDirectory(at: out, withIntermediateDirectories: true)
    let py = (try? String(contentsOf: gameRes.appendingPathComponent("tools/python"), encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    let p = Process(); p.executableURL = URL(fileURLWithPath: py.isEmpty ? "/usr/bin/env" : py)
    p.arguments = (py.isEmpty ? ["python3"] : []) + ["-B", tool.path, packDir.appendingPathComponent("pack.tsv").path, packDir.appendingPathComponent("included").path, gameRes.appendingPathComponent("romfs").path, out.path]
    p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
    do { try p.run(); p.waitUntilExit() } catch { return nil }
    guard p.terminationStatus == 0 else { return nil }
    try? key.write(to: stamp, atomically: true, encoding: .utf8)
    return stack
}
// What the converter reported for a mod: (ported, not convertible) file lists, from mods-ported/<mod>/port.tsv
func portReport(_ name: String) -> (ported: Int, skipped: [String]) {
    guard let t = try? String(contentsOf: portedDir.appendingPathComponent(name).appendingPathComponent("port.tsv"), encoding: .utf8) else { return (0, []) }
    var n = 0, sk: [String] = []
    for l in t.split(separator: "\n") { let f = l.split(separator: "\t", omittingEmptySubsequences: false); guard f.count >= 3 else { continue }
        if f[1] == "ported" { n += 1 } else if f[1] != "unchanged" { sk.append(String(f[0]).components(separatedBy: "/").last ?? String(f[0])) } }
    return (n, sk)
}
// Rebuild the overlay from the enabled mods (first in the order wins). Returns per-mod reports; an empty overlay when no mod is on
func buildOverlay(_ s: Settings) throws -> [String: ModReport] {
    let fm = FileManager.default
    try? fm.removeItem(at: overlayDir); try fm.createDirectory(at: overlayDir, withIntermediateDirectories: true)
    var reports: [String: ModReport] = [:]
    var enabled = s.modOrder.filter { s.mods[$0] == true }.map { modsDir.appendingPathComponent($0) }
    var packs: [(String, TexturePack)] = enabled.compactMap { d in loadPack(d.appendingPathComponent("_pack")).map { (d.lastPathComponent, $0) } }   // after the file mods, before PC textures
    enabled.removeAll { fm.fileExists(atPath: $0.appendingPathComponent("_pack/textures.index").path) }
    // The pack and the user's file mods are converted as one stack, lowest priority first (the pack, then the user's list from the bottom up): each mod is
    // merged onto the files of the ones below it, so two mods that change the same archive (menu text, menu textures) both keep their part. The top of
    // the stack holds every change; the per-mod reports come from each mod's own port.tsv.
    var stackTop: URL? = s.pack ? packStack() : nil
    var stackNames: [String] = []
    for d in enabled.reversed() {
        if fm.fileExists(atPath: d.appendingPathComponent("port.tsv").path) { continue }   // already converted elsewhere: laid as it is below
        stackTop = portedMod(modRoot(d), base: stackTop, name: d.lastPathComponent); stackNames.append(d.lastPathComponent)
    }
    enabled = enabled.filter { fm.fileExists(atPath: $0.appendingPathComponent("port.tsv").path) } + (stackTop.map { [$0] } ?? [])
    if let g = glyphSet(s) { enabled.append(g) }   // the button pictures come last among the mods: a mod that replaces the same font or menu archive wins
    if let p = texturePack(s) { packs.append(("PC textures", p)) }
    if enabled.isEmpty && packs.isEmpty { return reports }
    var bhd = [Data](), bdtSize = [UInt64](), index = [[UInt32: Int]](), appends = [Data]()   // per archive: index bytes, data size, hash → entry offset in the index
    for i in 0..<2 {
        let b = try Data(contentsOf: gameRes.appendingPathComponent("romfs/dvdbnd\(i).bhd5"))
        bhd.append(b); appends.append(Data())
        bdtSize.append(((try? fm.attributesOfItem(atPath: gameRes.appendingPathComponent("romfs/dvdbnd\(i).bdt").path)[.size]) as? UInt64) ?? 0)
        var m = [UInt32: Int]()
        func u32(_ o: Int) -> UInt32 { b.subdata(in: o..<o + 4).withUnsafeBytes { $0.loadUnaligned(as: UInt32.self) } }
        func u64(_ o: Int) -> UInt64 { b.subdata(in: o..<o + 8).withUnsafeBytes { $0.loadUnaligned(as: UInt64.self) } }
        let nb = Int(u64(0x10)), bo = Int(u64(0x18))
        for k in 0..<nb { let cnt = Int(u32(bo + k * 16)), off = Int(u64(bo + k * 16 + 8)); for e in 0..<cnt { m[u32(off + e * 16)] = off + e * 16 } }
        index.append(m)
    }
    var done = Set<UInt32>(), modHashes = Set<UInt32>()
    let glyphs = glyphSet(s)
    for dir in enabled {
        let isStack = dir == stackTop
        let name = isStack ? "Mods" : dir.lastPathComponent
        var r = ModReport()
        let src = dir   // everything here is already in Switch form: the converted stack, the button pictures, or a mod converted elsewhere (port.tsv at its root)
        for (rel, url) in modFiles(src) {
            if rel.hasSuffix(".tsv") || rel.hasSuffix("/.source") { continue }
            let path = rel.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            let h = path.hasPrefix("_hash/") ? (UInt32(path.dropFirst(6), radix: 16) ?? 0) : fsHash("/" + path)   // _hash/<8 hex>: an archive known only by its path hash
            guard let a = (0..<2).first(where: { index[$0][h] != nil }), let eo = index[a][h] else {
                // a loose RomFS file (movies: movww/frpg_title.mp4) goes into the overlay folder itself, which the host reads before the RomFS
                if fm.fileExists(atPath: gameRes.appendingPathComponent("romfs/" + path).path), !fm.fileExists(atPath: overlayDir.appendingPathComponent(path).path) {
                    let dst = overlayDir.appendingPathComponent(path)
                    try fm.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true)
                    try fm.copyItem(at: url, to: dst); r.replaced += 1; continue
                }
                if src == dir || dir == glyphs { r.unknown.append(rel) }; continue
            }
            if done.contains(h) { continue }   // an earlier mod in the order already replaced it
            let data = try Data(contentsOf: url)
            while appends[a].count % 16 != 0 { appends[a].append(0) }
            let off = bdtSize[a] + UInt64(appends[a].count)
            appends[a].append(data)
            var sz = UInt32(data.count), o = off
            bhd[a].replaceSubrange(eo + 4..<eo + 8, with: Data(bytes: &sz, count: 4))
            bhd[a].replaceSubrange(eo + 8..<eo + 16, with: Data(bytes: &o, count: 8))
            done.insert(h); modHashes.insert(h); r.replaced += 1
        }
        if isStack {   // one report line per stacked mod, from its converter report
            for n in stackNames { let pr = portReport(n); reports[n] = ModReport(replaced: pr.ported, unknown: pr.skipped) }
            if s.pack { reports["Recommended pack"] = ModReport(replaced: packMods().filter { $0.status == "included" }.count, unknown: []) }
            continue
        }
        reports[name] = r
    }
    // Texture packs (a big converted texture mod, then the PC textures): lower priority than every file mod. Each pack's textures.append is cloned
    // (APFS: no copy) into the archive's append, the packs back to back, then the mods' data; the mods' offsets above move past all packs.
    var base = [UInt64](repeating: 0, count: 2)   // per archive: bytes of packs laid so far in the append
    var parts = [[(URL, UInt64)]](repeating: [], count: 2)
    for (name, p) in packs {
        var r = ModReport(); var used = [false, false]
        for (a, h, off, size) in p.entries where index[a][h] != nil && !done.contains(h) {
            let eo = index[a][h]!; var sz = UInt32(size), o = bdtSize[a] + base[a] + off
            bhd[a].replaceSubrange(eo + 4..<eo + 8, with: Data(bytes: &sz, count: 4))
            bhd[a].replaceSubrange(eo + 8..<eo + 16, with: Data(bytes: &o, count: 8))
            done.insert(h); r.replaced += 1; used[a] = true
        }
        for a in 0..<2 where used[a] { parts[a].append((p.data, p.size)); base[a] += (p.size + 15) / 16 * 16 }
        reports[name] = r
    }
    for a in 0..<2 where base[a] > 0 {   // shift the file mods' entries of this archive past the packs
        for h in modHashes { if let eo = index[a][h] { var o = bhd[a].subdata(in: eo + 8..<eo + 16).withUnsafeBytes { $0.loadUnaligned(as: UInt64.self) } + base[a]
            bhd[a].replaceSubrange(eo + 8..<eo + 16, with: Data(bytes: &o, count: 8)) } }
    }
    for i in 0..<2 where !appends[i].isEmpty || !parts[i].isEmpty {
        try bhd[i].write(to: overlayDir.appendingPathComponent("dvdbnd\(i).bhd5"))
        let ap = overlayDir.appendingPathComponent("dvdbnd\(i).bdt.append")
        if parts[i].count == 1 && appends[i].isEmpty { try fm.createSymbolicLink(at: ap, withDestinationURL: parts[i][0].0); continue }   // one pack alone: no copy at all
        if let first = parts[i].first { try fm.copyItem(at: first.0, to: ap) } else { fm.createFile(atPath: ap.path, contents: nil) }   // APFS clone on the same volume
        let h = try FileHandle(forWritingTo: ap); defer { try? h.close() }
        for (k, (u, size)) in parts[i].enumerated() {   // each pack starts 16-aligned: pad after the previous one, then copy it (the first is the clone)
            if k > 0 {
                let src = try FileHandle(forReadingFrom: u); defer { try? src.close() }
                try h.seekToEnd(); while let c = try src.read(upToCount: 64 << 20), !c.isEmpty { h.write(c) }
            }
            try h.seekToEnd(); h.write(Data(count: Int((16 - size % 16) % 16)))
        }
        try h.seekToEnd(); h.write(appends[i])
    }
    return reports
}

// MARK: - PC textures. game/pctextures holds textures.append (Switch archives rebuilt with the PC version's textures where they are larger or better
// compressed: BC7 colour, BC5 normals) and textures.index (archive, path hash hex, offset, size, path per line). It is generated from the user's own PC copy
// of the game when the app is built (tools/dsr-pc-textures, install.sh --pc-game); the release never contains game data.
struct TexturePack { let data: URL; let size: UInt64; let entries: [(Int, UInt32, UInt64, UInt64)] }
func texturePackDir() -> URL { gameRes.appendingPathComponent("pctextures") }
func texturePackAvailable() -> Bool { FileManager.default.fileExists(atPath: texturePackDir().appendingPathComponent("textures.index").path) }
func texturePack(_ s: Settings) -> TexturePack? {
    guard s.textures == "pc", texturePackAvailable() else { return nil }
    return loadPack(texturePackDir())
}
// A big texture mod converted elsewhere ships the same way: mods/<name>/_pack/textures.append + textures.index (no copy into the overlay, cloned)
func loadPack(_ d: URL) -> TexturePack? {
    let data = d.appendingPathComponent("textures.append")
    guard let txt = try? String(contentsOf: d.appendingPathComponent("textures.index"), encoding: .utf8),
          let size = (try? FileManager.default.attributesOfItem(atPath: data.path)[.size]) as? UInt64 else { return nil }
    var e: [(Int, UInt32, UInt64, UInt64)] = []
    for l in txt.split(separator: "\n") { let f = l.split(separator: "\t"); if f.count >= 4, let a = Int(f[0]), let h = UInt32(f[1], radix: 16), let o = UInt64(f[2]), let n = UInt64(f[3]) { e.append((a, h, o, n)) } }
    return TexturePack(data: data, size: size, entries: e)
}

// MARK: - Button pictures. The game draws its button prompts from a font icon page (DSFont24_1000 in /font/<lang>/DSFont24*.tpf.dcx) and the inventory
// tab keycaps (Menu11 in two menu archives). game/glyphs/<ps|xbox>-<position|label> hold those archives redrawn from the user's own RomFS when the
// app is built (tools/dsr-glyphs/dsr_glyphs.py), installed like a mod. "position"/"label" follows the face-button setting so the picture always names the
// button that does the action.
enum Pad { case none, playstation, xbox, other }
func connectedPad(wait: TimeInterval = 0) -> Pad {   // GameController lists controllers a moment after launch: wait up to `wait` seconds for one
    let end = Date().addingTimeInterval(wait)
    while GCController.controllers().first(where: { $0.extendedGamepad != nil }) == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
    guard let c = GCController.controllers().first(where: { $0.extendedGamepad != nil }) else { return .none }
    let g = c.extendedGamepad, cat = (c.productCategory + " " + (c.vendorName ?? "")).lowercased()
    if g is GCDualSenseGamepad || g is GCDualShockGamepad || cat.contains("dualsense") || cat.contains("dualshock") || cat.contains("playstation") { return .playstation }
    if g is GCXboxGamepad || cat.contains("xbox") { return .xbox }
    return .other
}
func promptFamily(_ s: Settings, wait: TimeInterval = 0) -> String {   // switch, playstation or xbox
    if s.buttonPrompts != "auto" { return s.buttonPrompts }
    switch connectedPad(wait: wait) { case .playstation: return "playstation"; case .xbox: return "xbox"; default: return "switch" }
}
var promptWait: TimeInterval = 0
func glyphSet(_ s: Settings) -> URL? {
    let f = promptFamily(s, wait: promptWait); guard f != "switch" else { return nil }
    let d = gameRes.appendingPathComponent("glyphs/\(f == "playstation" ? "ps" : "xbox")-\(s.faceButtons == "label" ? "label" : "position")")
    return FileManager.default.fileExists(atPath: d.path) ? d.resolvingSymlinksInPath() : nil   // the enumerator does not enter a symlinked folder
}


// MARK: - Game
final class Game: ObservableObject {
    @Published var running = false
    @Published var lastExit: Int32 = 0
    var proc: Process?
    func env(_ s: Settings, overlay: Bool) -> [String: String] {
        var e = ProcessInfo.processInfo.environment
        let r = gameRes.path
        e["DM_AUDIO"] = "1"; e["DM_ROOT"] = support.path; e["DM_ROMFS"] = r + "/romfs"; e["DM_SAVE"] = saveDir.path
        e["DM_TEMP"] = support.appendingPathComponent("temp").path; e["DM_MSL_DIR"] = r + "/msl"; e["DM_WINDOW"] = "1"
        e["DM_GAMES_DIR"] = r + "/games"; e["DM_NVN_SHMAP"] = r + "/games/01004AB00A260000/shader_map.tsv"
        if FileManager.default.fileExists(atPath: r + "/font") { e["DM_FONT_DIR"] = r + "/font" }
        if overlay { e["DM_ROMFS_OVERLAY"] = overlayDir.path }
        e["DM_PRESENT_HZ"] = String(s.fps)
        if s.fps != 60 { e["DM_PRESENT_LINK"] = "0" }   // classic present: the display-link path holds the game at 60
        if s.fps != 60 && e["DM_SPIN_US"] == nil { e["DM_SPIN_US"] = "30" }   // above 60 the game's threads hand work over many times per 8.3 ms frame: a 30 µs spin before sleeping keeps them on time (M2 windowless at 120: frames > 12 ms 6.2 -> 3.9 %, p99 25.7 -> 15.8 ms; 60 warps and 20 Continue boots without a hang)
        if s.resolution != 1080 { e["DM_MEM_RESERVE"] = "0x200000000"; e["DM_APP_POOL"] = "0x1A0000000" }   // bigger targets need a larger guest heap and allocator pool
        if s.fullscreen { e["DM_FULLSCREEN"] = "1" }
        if !s.colorspace.isEmpty { e["DM_LAYER_COLORSPACE"] = s.colorspace }
        if s.record { e["DM_PADLOG"] = "1"; e["DM_KEYLOG"] = "1" }
        if s.perfOverlay { e["MTL_HUD_ENABLED"] = "1" }
        if s.faceButtons == "label" { e["DM_FACE_BUTTONS"] = "label" }
        e["DM_VOLUME"] = String(Int(s.volume))
        return e
    }
    func main(_ s: Settings) -> String {
        let res = s.resolution == 2160 ? "4k" : s.resolution == 1440 ? "2k" : ""
        return "main\(res)\(s.fps)"
    }
    func launch(_ s: Settings, onExit: @escaping () -> Void) {
        let fm = FileManager.default
        for d in [saveDir, support.appendingPathComponent("temp"), modsDir] { try? fm.createDirectory(at: d, withIntermediateDirectories: true) }
        promptWait = 1.5; defer { promptWait = 0 }   // at Play, give a controller that is just waking up a moment to appear
        let overlay = (try? buildOverlay(s)).map { !$0.isEmpty } ?? false
        let p = Process()
        p.executableURL = bundleMacOS.appendingPathComponent("dmhost")
        p.arguments = [gameRes.appendingPathComponent(main(s)).path]
        p.environment = env(s, overlay: overlay)
        if fm.fileExists(atPath: logFile.path), let a = try? fm.attributesOfItem(atPath: logFile.path), let d = a[.modificationDate] as? Date {   // keep the previous run's log
            let f = DateFormatter(); f.dateFormat = "yyyyMMdd-HHmmss"; let old = support.appendingPathComponent("logs"); try? fm.createDirectory(at: old, withIntermediateDirectories: true)
            try? fm.moveItem(at: logFile, to: old.appendingPathComponent("run-\(f.string(from: d)).log"))
            for u in ((try? fm.contentsOfDirectory(at: old, includingPropertiesForKeys: nil)) ?? []).sorted(by: { $0.path > $1.path }).dropFirst(10) { try? fm.removeItem(at: u) }   // last 10 runs
        }
        fm.createFile(atPath: logFile.path, contents: nil)
        if let h = try? FileHandle(forWritingTo: logFile) { p.standardOutput = h; p.standardError = h }
        p.terminationHandler = { pr in DispatchQueue.main.async { self.running = false; self.lastExit = pr.terminationStatus; onExit() } }
        do { try p.run(); proc = p; running = true } catch { lastExit = -1; onExit() }
    }
}

// MARK: - Views
enum Pane: String, CaseIterable, Identifiable { case play, graphics, controls, audio, mods, saves, about; var id: String { rawValue } }
extension Pane {
    var title: String {
        switch self {
        case .play: return T("Play", "Jouer"); case .graphics: return T("Graphics", "Graphismes"); case .controls: return T("Controls", "Commandes")
        case .audio: return T("Audio", "Audio"); case .mods: return T("Mods", "Mods"); case .saves: return T("Saves", "Sauvegardes"); case .about: return T("About", "À propos")
        }
    }
    var icon: String {
        switch self {
        case .play: return "play.fill"; case .graphics: return "display"; case .controls: return "gamecontroller"; case .audio: return "speaker.wave.2"
        case .mods: return "puzzlepiece.extension"; case .saves: return "externaldrive"; case .about: return "info.circle"
        }
    }
}

struct ContentView: View {
    @State var s = loadSettings()
    @State var pane: Pane? = CommandLine.arguments.firstIndex(of: "--pane").flatMap { i in i + 1 < CommandLine.arguments.count ? Pane(rawValue: CommandLine.arguments[i + 1]) : nil } ?? .play   // --pane <name>: open on that pane (screenshots)
    @StateObject var game = Game()
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(Pane.allCases) { p in
                    Button { pane = p } label: {
                        Label(p.title, systemImage: p.icon).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 6).padding(.horizontal, 10)
                            .background(RoundedRectangle(cornerRadius: 7).fill(pane == p ? Color.accentColor : .clear))
                            .foregroundStyle(pane == p ? Color.white : Color.primary).contentShape(Rectangle())
                    }.buttonStyle(.plain)
                }
                Spacer()
            }.padding(10).frame(width: 190).background(.regularMaterial)
            Divider()
            Group {
                switch pane ?? .play {
                case .play: PlayPane(s: $s, game: game)
                case .graphics: GraphicsPane(s: $s)
                case .controls: ControlsPane(s: $s)
                case .audio: AudioPane(s: $s)
                case .mods: ModsPane(s: $s)
                case .saves: SavesPane()
                case .about: AboutPane(s: $s)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(minWidth: 820, minHeight: 540)
        .onChange(of: s) { _, n in saveSettings(n) }
    }
}

func play(_ s: Settings, _ game: Game) {
    saveSettings(s)
    NSApp.windows.forEach { $0.orderOut(nil) }
    game.launch(s) {
        if s.skipWindow && game.lastExit == 0 { NSApp.terminate(nil) }
        NSApp.windows.first?.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
}

struct PlayPane: View {
    @Binding var s: Settings
    @ObservedObject var game: Game
    var summary: String {
        let r = s.resolution == 2160 ? "4K (3840×2160)" : s.resolution == 1440 ? "1440p (2560×1440)" : "1080p (1920×1080)"
        return "\(r) · \(s.fps) \(T("fps", "i/s")) · \(s.fullscreen ? T("Fullscreen", "Plein écran") : T("Window", "Fenêtre"))"
    }
    var activeMods: Int { s.modOrder.filter { s.mods[$0] == true }.count }
    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            if let img = NSImage(contentsOf: bundleRes.appendingPathComponent("AppIcon.icns")) ?? NSImage(named: "AppIcon") {
                Image(nsImage: img).resizable().interpolation(.high).frame(width: 180, height: 180).clipShape(RoundedRectangle(cornerRadius: 28)).shadow(radius: 12)
            }
            Text("DARK SOULS: REMASTERED").font(.system(size: 26, weight: .semibold, design: .serif)).tracking(2)
            Text(summary).foregroundStyle(.secondary)
            if activeMods > 0 { Text(T("\(activeMods) mod(s) active", "\(activeMods) mod(s) actif(s)")).font(.callout).foregroundStyle(.orange) }
            Button { play(s, game) } label: { Text(game.running ? T("Running…", "En cours…") : T("Play", "Jouer")).font(.title2.weight(.semibold)).frame(width: 220, height: 44) }
                .buttonStyle(.borderedProminent).controlSize(.large).keyboardShortcut(.defaultAction).disabled(game.running)
            if game.lastExit != 0 && !game.running {
                Text(T("The game ended unexpectedly (code \(game.lastExit)). The log is in About.", "Le jeu s'est arrêté de façon inattendue (code \(game.lastExit)). Le journal est dans À propos."))
                    .font(.callout).foregroundStyle(.red)
            }
            Toggle(T("Skip this window next time (hold ⌥ Option at launch to see it)", "Passer cette fenêtre la prochaine fois (maintenir ⌥ Option au lancement pour la revoir)"), isOn: $s.skipWindow)
                .toggleStyle(.checkbox).font(.callout).foregroundStyle(.secondary)
            Spacer()
            Text(T("In game: ⌘F fullscreen · ⌘Q quit", "En jeu : ⌘F plein écran · ⌘Q quitter")).font(.caption).foregroundStyle(.tertiary)
        }.frame(maxWidth: .infinity).padding()
    }
}

struct Section<C: View>: View {
    let title: String; let note: String?; @ViewBuilder let content: C
    init(_ title: String, note: String? = nil, @ViewBuilder content: () -> C) { self.title = title; self.note = note; self.content = content() }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            content
            if let n = note { Text(n).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }
        }
    }
}

func displayHz() -> Int { NSScreen.screens.map { $0.maximumFramesPerSecond }.max() ?? 60 }

struct GraphicsPane: View {
    @Binding var s: Settings
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Section(T("Internal resolution", "Résolution interne"), note: T("Every pass of the game renders at this size; MetalFX then scales the picture to your window or screen.", "Chaque passe du jeu est rendue à cette taille ; MetalFX met ensuite l'image à l'échelle de la fenêtre ou de l'écran.")) {
                    Picker("", selection: $s.resolution) { Text("1080p").tag(1080); Text("1440p (2K)").tag(1440); Text("4K").tag(2160) }.pickerStyle(.segmented).labelsHidden().frame(width: 320)
                }
                Section(T("Frame rate", "Images par seconde"), note: fpsNote) {
                    Picker("", selection: $s.fps) { Text("60").tag(60); Text("90").tag(90); Text("120").tag(120) }.pickerStyle(.segmented).labelsHidden().frame(width: 240)
                }
                Section(T("Display", "Affichage")) {
                    Picker("", selection: $s.fullscreen) { Text(T("Window", "Fenêtre")).tag(false); Text(T("Fullscreen", "Plein écran")).tag(true) }.pickerStyle(.segmented).labelsHidden().frame(width: 240)
                }
                Section(T("Textures", "Textures"), note: texturesNote) {
                    Picker("", selection: $s.textures) { Text("Switch").tag("switch"); Text(T("PC (from your PC copy)", "PC (depuis votre copie PC)")).tag("pc") }
                        .pickerStyle(.segmented).labelsHidden().frame(width: 360).disabled(!texturePackAvailable())
                }
                Section(T("Performance overlay", "Overlay de performance"), note: T("Metal's HUD: frame rate, frame time, GPU time and resolution.", "Le HUD de Metal : images par seconde, temps d'image, temps GPU et résolution.")) {
                    Toggle(T("Show", "Afficher"), isOn: $s.perfOverlay)
                }
            }.padding(24)
        }
    }
    var texturesNote: String {
        texturePackAvailable()
            ? T("PC: the PC version's textures wherever they are sharper (up to 4x the pixels, BC7 colour, BC5 normals). Uses more memory and disk.", "PC : les textures de la version PC partout où elles sont plus nettes (jusqu'à 4x les pixels, couleur BC7, normales BC5). Utilise plus de mémoire et de disque.")
            : T("Not installed: build the app with your PC copy of the game (./install.sh ... --pc-game <folder with chr, map, parts>).", "Non installé : construisez l'app avec votre copie PC du jeu (./install.sh ... --pc-game <dossier avec chr, map, parts>).")
    }
    var fpsNote: String {
        let hz = displayHz()
        var n = T("The game advances by the real frame time: below the chosen rate it stays at normal speed.", "Le jeu avance selon le temps réel de chaque image : sous le taux choisi, il garde sa vitesse normale.")
        if s.fps > hz { n += " " + T("Your display refreshes at \(hz) Hz: frames beyond that are not shown.", "Votre écran rafraîchit à \(hz) Hz : les images au-delà ne sont pas affichées.") }
        return n
    }
}

struct ControlsPane: View {
    @Binding var s: Settings
    @State var pads: [String] = []
    let keys: [(String, String)] = [("WASD", T("Move (left stick)", "Se déplacer (stick gauche)")), ("↑ ↓ ← →", T("D-pad", "Croix directionnelle")), ("J", "A"), ("K", "B"), ("U", "X"), ("I", "Y"),
                                     ("Q / E", "L / R"), ("Z / C", "ZL / ZR"), ("F / G", T("Stick clicks", "Clic des sticks")), ("Return", "+"), ("Tab", "−")]
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                Section(T("Controllers", "Manettes")) {
                    if pads.isEmpty { Text(T("No controller connected: the keyboard works.", "Aucune manette connectée : le clavier fonctionne.")).foregroundStyle(.secondary) }
                    ForEach(pads, id: \.self) { Label($0, systemImage: "gamecontroller.fill") }
                }
                Section(T("Face buttons", "Boutons de façade"), note: T("By position: the confirm button is the bottom one, as on Xbox and PlayStation (Nintendo's A is on the right). By label: the button marked A confirms.", "Par position : le bouton de validation est celui du bas, comme sur Xbox et PlayStation (le A de Nintendo est à droite). Par étiquette : le bouton marqué A valide.")) {
                    Picker("", selection: $s.faceButtons) { Text(T("By position", "Par position")).tag("position"); Text(T("By label", "Par étiquette")).tag("label") }.pickerStyle(.segmented).labelsHidden().frame(width: 300)
                }
                Section(T("Button prompts", "Icônes des boutons"), note: promptNote) {
                    Picker("", selection: $s.buttonPrompts) {
                        Text(T("Auto", "Auto")).tag("auto"); Text("Switch").tag("switch"); Text("PlayStation").tag("playstation"); Text("Xbox").tag("xbox")
                    }.pickerStyle(.segmented).labelsHidden().frame(width: 360)
                }
                Section(T("Keyboard", "Clavier")) {
                    Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 4) {
                        ForEach(keys, id: \.0) { k in GridRow { Text(k.0).font(.system(.body, design: .monospaced)); Text(k.1).foregroundStyle(.secondary) } }
                    }
                }
            }.padding(24)
        }
        .onAppear(perform: refresh)
        .onReceive(NotificationCenter.default.publisher(for: .GCControllerDidConnect)) { _ in refresh() }
        .onReceive(NotificationCenter.default.publisher(for: .GCControllerDidDisconnect)) { _ in refresh() }
    }
    func refresh() { pads = GCController.controllers().map { $0.vendorName ?? T("Controller", "Manette") } }
    var promptNote: String {
        let f = promptFamily(s), name = f == "playstation" ? "PlayStation" : f == "xbox" ? "Xbox" : "Switch"
        let now = s.buttonPrompts == "auto" ? T(" Now: \(name).", " Actuellement : \(name).") : ""
        return T("The buttons shown in the game's menus and messages. Auto follows the controller connected when you press Play (Switch letters with the keyboard).", "Les boutons affichés dans les menus et messages du jeu. Auto suit la manette branchée au moment de Jouer (lettres Switch au clavier).") + now
    }
}

struct AudioPane: View {
    @Binding var s: Settings
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            Section(T("Master volume", "Volume général")) {
                HStack { Image(systemName: "speaker.fill"); Slider(value: $s.volume, in: 0...100, step: 5).frame(width: 280); Image(systemName: "speaker.wave.3.fill"); Text("\(Int(s.volume)) %").monospacedDigit().frame(width: 50) }
            }
        }.padding(24)
    }
}

struct ModsPane: View {
    @Binding var s: Settings
    @State var report: [String: ModReport] = [:]
    @State var msg = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            PackView(s: $s, installed: Set(s.modOrder))
            Divider()
            Text(T("Your mods. Any mod made for Dark Souls Remastered on PC: add the file you downloaded (.zip, .7z, .rar or a folder) and the app converts it for this version. Mods that change the program (DLL) do not work.",
                   "Vos mods. Tout mod fait pour Dark Souls Remastered sur PC : ajoutez le fichier téléchargé (.zip, .7z, .rar ou dossier), l'app le convertit pour cette version. Les mods qui modifient le programme (DLL) ne fonctionnent pas."))
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(T("Add a mod…", "Ajouter un mod…")) { add() }
                Button(T("Open the mods folder", "Ouvrir le dossier des mods")) { try? FileManager.default.createDirectory(at: modsDir, withIntermediateDirectories: true); NSWorkspace.shared.open(modsDir) }
                Button(T("Check", "Vérifier")) { check() }
            }
            ScrollView { VStack(spacing: 0) {
                ForEach(s.modOrder, id: \.self) { m in
                    HStack {
                        Toggle("", isOn: Binding(get: { s.mods[m] ?? false }, set: { s.mods[m] = $0 })).labelsHidden()
                        VStack(alignment: .leading) {
                            Text(m)
                            if let r = report[m] {
                                Text(T("\(r.replaced) file(s) replaced", "\(r.replaced) fichier(s) remplacé(s)") + (r.unknown.isEmpty ? "" : " · " + T("\(r.unknown.count) not in the game (ignored): ", "\(r.unknown.count) absent(s) du jeu (ignoré(s)) : ") + r.unknown.prefix(3).joined(separator: ", ")))
                                    .font(.caption).foregroundStyle(r.unknown.isEmpty ? Color.secondary : Color.orange)
                            }
                        }
                        Spacer()
                        Button { move(m, -1) } label: { Image(systemName: "chevron.up") }.buttonStyle(.borderless).disabled(s.modOrder.first == m)
                        Button { move(m, 1) } label: { Image(systemName: "chevron.down") }.buttonStyle(.borderless).disabled(s.modOrder.last == m)
                        Button { NSWorkspace.shared.open(modsDir.appendingPathComponent(m)) } label: { Image(systemName: "folder") }.buttonStyle(.borderless)
                    }.padding(.vertical, 6)
                    Divider()
                }
                if s.modOrder.isEmpty { Text(T("No mod yet.", "Aucun mod pour l'instant.")).foregroundStyle(.secondary).padding(.top, 30) }
            } }
            Text(T("Order = priority: when two mods replace the same file, the higher one wins.", "L'ordre fixe la priorité : quand deux mods remplacent le même fichier, celui du haut l'emporte.")).font(.caption).foregroundStyle(.secondary)
            if !msg.isEmpty { Text(msg).font(.caption) }
        }.padding(24).onAppear(perform: scan)
    }
    func move(_ m: String, _ d: Int) { guard let i = s.modOrder.firstIndex(of: m), (0..<s.modOrder.count).contains(i + d) else { return }; s.modOrder.swapAt(i, i + d) }
    func scan() {
        let names = ((try? FileManager.default.contentsOfDirectory(atPath: modsDir.path)) ?? []).filter { !$0.hasPrefix(".") }.sorted()
        s.modOrder = s.modOrder.filter { names.contains($0) } + names.filter { !s.modOrder.contains($0) }
        for n in names where s.mods[n] == nil { s.mods[n] = true }
    }
    func add() {
        let p = NSOpenPanel(); p.canChooseDirectories = true; p.canChooseFiles = true; p.allowsMultipleSelection = true
        p.allowedContentTypes = [.folder, .zip, UTType(filenameExtension: "7z") ?? .archive, UTType(filenameExtension: "rar") ?? .archive, .archive]
        p.message = T("Choose a mod: .zip, .7z, .rar or a folder", "Choisissez un mod : .zip, .7z, .rar ou dossier")
        guard p.runModal() == .OK else { return }
        try? FileManager.default.createDirectory(at: modsDir, withIntermediateDirectories: true)
        for u in p.urls {
            let name = u.deletingPathExtension().lastPathComponent, dest = modsDir.appendingPathComponent(name)
            try? FileManager.default.removeItem(at: dest)
            if ["zip", "7z", "rar"].contains(u.pathExtension.lowercased()) {   // macOS's bsdtar (libarchive) opens all three
                try? FileManager.default.createDirectory(at: dest, withIntermediateDirectories: true)
                let t = Process(); t.executableURL = URL(fileURLWithPath: "/usr/bin/bsdtar"); t.arguments = ["-xf", u.path, "-C", dest.path]; try? t.run(); t.waitUntilExit()
            } else { try? FileManager.default.copyItem(at: u, to: dest) }
        }
        scan(); check()
    }
    func check() {
        do { report = try buildOverlay(s); msg = T("Checked.", "Vérifié.") } catch { msg = T("Error: ", "Erreur : ") + error.localizedDescription }
    }
}

struct PackView: View {
    @Binding var s: Settings
    let installed: Set<String>
    var body: some View {
        let mods = packMods(), inc = mods.filter { $0.status == "included" }, dl = mods.filter { $0.status != "included" }
        VStack(alignment: .leading, spacing: 8) {
            Toggle(isOn: $s.pack) { Text(T("Recommended mod pack", "Pack de mods recommandé")).font(.headline) }.toggleStyle(.switch)
            Text(T("The best mods for this version, chosen and tested. \(inc.count) are included: their authors allow sharing them, they are converted the first time you play. \(dl.count) more cannot be shared (their authors' choice): download each one from Nexus and add it below, the app converts it.",
                   "Les meilleurs mods pour cette version, choisis et testés. \(inc.count) sont inclus : leurs auteurs autorisent leur partage, ils sont convertis à la première partie. \(dl.count) autres ne peuvent pas être partagés (choix de leurs auteurs) : téléchargez-les sur Nexus et ajoutez-les plus bas, l'app les convertit."))
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            DisclosureGroup(T("Included (\(inc.count))", "Inclus (\(inc.count))")) {
                ForEach(inc) { m in row(m, trailing: AnyView(EmptyView())) }
            }
            DisclosureGroup(T("To download (\(dl.count))", "À télécharger (\(dl.count))")) {
                ForEach(dl) { m in
                    row(m, trailing: AnyView(HStack {
                        if installed.contains(where: { $0.localizedCaseInsensitiveContains(m.folder) || $0.localizedCaseInsensitiveContains(m.id) }) { Image(systemName: "checkmark.circle.fill").foregroundStyle(.green) }
                        Button(T("Nexus page", "Page Nexus")) { if let u = URL(string: m.nexus + "?tab=files") { NSWorkspace.shared.open(u) } }
                    }))
                }
            }
        }
    }
    func row(_ m: PackMod, trailing: AnyView) -> some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 2) {
                Text(m.name).font(.callout.weight(.medium))
                Text(m.what).font(.caption).foregroundStyle(.secondary)
                Text(T("by ", "par ") + m.author).font(.caption2).foregroundStyle(.tertiary)
            }
            Spacer(); trailing
        }.padding(.vertical, 3)
    }
}

struct SavesPane: View {
    @State var backups: [URL] = []
    @State var msg = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(T("Your save is kept in Application Support. Back it up before trying mods.", "Votre sauvegarde est conservée dans Application Support. Faites-en une copie avant d'essayer des mods.")).font(.callout).foregroundStyle(.secondary)
            HStack {
                Button(T("Back up now", "Sauvegarder maintenant")) { backup() }
                Button(T("Open the save folder", "Ouvrir le dossier de sauvegarde")) { NSWorkspace.shared.open(saveDir) }
            }
            ScrollView { VStack(spacing: 0) {
                ForEach(backups, id: \.self) { b in
                    HStack { Image(systemName: "clock.arrow.circlepath"); Text(b.lastPathComponent); Spacer(); Button(T("Restore", "Restaurer")) { restore(b) } }.padding(.vertical, 6)
                    Divider()
                }
                if backups.isEmpty { Text(T("No backup yet.", "Aucune copie pour l'instant.")).foregroundStyle(.secondary).padding(.top, 30) }
            } }
            if !msg.isEmpty { Text(msg).font(.caption) }
        }.padding(24).onAppear(perform: list)
    }
    func list() { backups = ((try? FileManager.default.contentsOfDirectory(at: backupsDir, includingPropertiesForKeys: nil)) ?? []).sorted { $0.lastPathComponent > $1.lastPathComponent } }
    func backup() {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd HH.mm.ss"
        let d = backupsDir.appendingPathComponent(f.string(from: Date()))
        do { try FileManager.default.createDirectory(at: backupsDir, withIntermediateDirectories: true); try FileManager.default.copyItem(at: saveDir, to: d); msg = T("Saved.", "Sauvegardé.") } catch { msg = error.localizedDescription }
        list()
    }
    func restore(_ b: URL) {
        let a = NSAlert(); a.messageText = T("Restore this backup?", "Restaurer cette sauvegarde ?")
        a.informativeText = T("Your current save is backed up first, then replaced by \(b.lastPathComponent).", "Votre sauvegarde actuelle est d'abord copiée, puis remplacée par \(b.lastPathComponent).")
        a.addButton(withTitle: T("Restore", "Restaurer")); a.addButton(withTitle: T("Cancel", "Annuler"))
        guard a.runModal() == .alertFirstButtonReturn else { return }
        backup()
        do { try FileManager.default.removeItem(at: saveDir); try FileManager.default.copyItem(at: b, to: saveDir); msg = T("Restored.", "Restaurée.") } catch { msg = error.localizedDescription }
    }
}

struct AboutPane: View {
    @Binding var s: Settings
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("DARK SOULS: REMASTERED").font(.title3.weight(.semibold))
            Text(T("Native Mac port, nxnative. Game update 1.0.3. The game itself is © BANDAI NAMCO Entertainment Inc. / © FromSoftware, Inc.; this port uses your own copy.", "Portage natif Mac, nxnative. Mise à jour du jeu 1.0.3. Le jeu lui-même est © BANDAI NAMCO Entertainment Inc. / © FromSoftware, Inc. ; ce portage utilise votre propre copie.")).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            HStack {
                Button(T("Open the last log", "Ouvrir le dernier journal")) { NSWorkspace.shared.open(logFile) }
                Button(T("Open the data folder", "Ouvrir le dossier des données")) { NSWorkspace.shared.open(support) }
                Button(T("Reset settings", "Réinitialiser les réglages")) { let k = s; s = Settings(); s.mods = k.mods; s.modOrder = k.modOrder }
            }
        }.padding(24)
    }
}

// MARK: - App
final class Delegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ a: NSApplication) -> Bool { true }
}
@main
struct LauncherApp: App {
    @NSApplicationDelegateAdaptor(Delegate.self) var delegate
    init() {
        try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        // CLI: DarkSouls --build-overlay (rebuild the mods overlay and print the reports, for tests)
        if CommandLine.arguments.contains("--build-overlay") {
            let r = (try? buildOverlay(loadSettings())) ?? [:]
            print("button prompts: \(promptFamily(loadSettings(), wait: 1.5)) -> \(glyphSet(loadSettings())?.path ?? "none (Switch)")")
            for (k, v) in r { print("\(k): \(v.replaced) replaced, \(v.unknown.count) unknown \(v.unknown.prefix(5))") }
            exit(0)
        }
        // CLI: DarkSouls --print-env (the game folder, the command and the environment Play would use, for tests)
        if CommandLine.arguments.contains("--print-env") {
            let s = loadSettings(), g = Game()
            print("game \(gameRes.path)\ncommand \(bundleMacOS.appendingPathComponent("dmhost").path) \(gameRes.appendingPathComponent(g.main(s)).path)")
            for (k, v) in g.env(s, overlay: false) where k.hasPrefix("DM_") { print("env \(k)=\(v)") }
            exit(0)
        }
        let s = loadSettings()
        if s.skipWindow && !NSEvent.modifierFlags.contains(.option) {   // straight into the game; quit with it
            let g = Game(); quick = g
            DispatchQueue.main.async { NSApp.windows.forEach { $0.orderOut(nil) }; g.launch(s) { if g.lastExit == 0 { NSApp.terminate(nil) } else { NSApp.windows.first?.makeKeyAndOrderFront(nil) } } }
        }
    }
    var body: some Scene {
        WindowGroup("Dark Souls Remastered") { ContentView() }.windowResizability(.contentMinSize).commands { CommandGroup(replacing: .newItem) {} }
    }
}
var quick: Game?
