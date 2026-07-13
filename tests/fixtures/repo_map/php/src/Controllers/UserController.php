<?php

namespace App\Controllers;

use App\Models\User;
use Monolog\Logger;

require __DIR__ . '/../helpers.php';

class UserController
{
    public function show(): User
    {
        return new User();
    }
}
