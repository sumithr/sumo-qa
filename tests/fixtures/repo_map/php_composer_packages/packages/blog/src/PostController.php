<?php

namespace Blog;

use Blog\Post;

class PostController
{
    public function latest(): Post
    {
        return new Post();
    }
}
