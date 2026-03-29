import { setupServer } from "msw/node";

import { appHandlers } from "./handlers/app";

export const server = setupServer(...appHandlers);
