import { access } from "node:fs/promises";
import { resolve } from "node:path";

const contractPath = resolve(process.cwd(), "../../packages/contracts/openapi/openapi-v1.json");

await access(contractPath);
console.log(`OpenAPI contract found: ${contractPath}`);
