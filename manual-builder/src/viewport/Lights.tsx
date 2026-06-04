/** Shared scene background + lighting, used by every viewport canvas. */
export function Lights() {
  return (
    <>
      <color attach="background" args={["#eef2f6"]} />
      <ambientLight intensity={0.75} />
      <hemisphereLight args={["#ffffff", "#aab3bd", 0.55]} />
      <directionalLight position={[1500, 2200, 1800]} intensity={0.7} />
      <directionalLight position={[-1600, 1000, -1400]} intensity={0.3} />
    </>
  );
}
