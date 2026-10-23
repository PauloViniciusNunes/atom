dependencies = {
    1: [],
    2: [1],
    3: [1,2]
}

visiting = set()
visited = set()

# Caminha
def visit(step_id: int) -> None:
    if step_id in visiting:
        raise ValueError(
            "O plano possui dependências circulares."
        )

    if step_id in visited:
        return

    print(step_id)
    visiting.add(step_id)

    for dependency_id in dependencies[step_id]:
        visit(dependency_id)

    visiting.remove(step_id)
    visited.add(step_id)

visit(3)