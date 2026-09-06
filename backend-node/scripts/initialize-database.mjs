import { connectDatabase, disconnectDatabase, initializeDatabase } from "../src/db.js";

try {
  await connectDatabase();
  await initializeDatabase();
  console.log("MongoDB Atlas schema and indexes are ready.");
} finally {
  await disconnectDatabase();
}
