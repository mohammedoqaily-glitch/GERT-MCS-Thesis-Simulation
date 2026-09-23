import fs from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const directory = process.argv[2];
if (!directory) throw new Error("Usage: node render_svgs.mjs <figure-directory>");
const names = (await fs.readdir(directory)).filter((name) => name.toLowerCase().endsWith(".svg")).sort();
for (const name of names) {
  const source = path.join(directory, name);
  const destination = path.join(directory, name.replace(/\.svg$/i, ".png"));
  await sharp(source, { density: 180 }).png({ compressionLevel: 9 }).toFile(destination);
}
console.log(JSON.stringify({ converted: names.length, directory }));
